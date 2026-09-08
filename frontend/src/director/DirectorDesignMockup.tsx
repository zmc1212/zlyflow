import { useState } from "react"
import { Button, Segmented, Tag, Tooltip } from "antd"
import { Check, ChevronLeft, ChevronRight, Clapperboard, Download, Film, Image, MoreHorizontal, Play, Plus, Sparkles, Wand2 } from "lucide-react"

const shots = [
  { id: "01", title: "雨夜，霓虹落在玻璃上", meta: "00:00 — 00:04", tone: "violet", status: "已完成" },
  { id: "02", title: "她抬头，看见远处的灯", meta: "00:04 — 00:09", tone: "blue", status: "生成中" },
  { id: "03", title: "列车驶过，风吹起衣角", meta: "00:09 — 00:14", tone: "orange", status: "待生成" },
  { id: "04", title: "手里的纸条被重新折好", meta: "00:14 — 00:18", tone: "green", status: "待生成" },
]

export default function DirectorDesignMockup() {
  const [view, setView] = useState("方案")
  const [selected, setSelected] = useState("02")
  const current = shots.find((shot) => shot.id === selected) ?? shots[1]

  return (
    <div className="director-mockup">
      <header className="director-mockup-topbar">
        <div className="director-mockup-brand"><span className="director-mockup-mark"><Clapperboard size={17} /></span><span>导演台</span><span className="director-mockup-slash">/</span><strong>雨夜候车室</strong></div>
        <Segmented value={view} onChange={(value) => setView(String(value))} options={["方案", "剪辑"]} />
        <div className="director-mockup-actions"><span className="director-save-state"><Check size={14} /> 已保存</span><Tooltip title="更多"><Button type="text" icon={<MoreHorizontal size={18} />} /></Tooltip><Button icon={<Download size={15} />}>导出</Button><Button type="primary" icon={<Sparkles size={15} />}>生成全部</Button></div>
      </header>
      <div className="director-mockup-body">
        <aside className="director-mockup-rail">
          <div className="director-rail-heading"><span>创作流程</span><button type="button"><Plus size={14} /></button></div>
          {[{ label: "方案", icon: Wand2, done: true }, { label: "镜头制作", icon: Film, active: true }, { label: "声音", icon: Sparkles }, { label: "交付", icon: Download }].map(({ label, icon: Icon, done, active }) => <button type="button" className={`director-rail-item ${active ? "is-active" : ""}`} key={label}><span className="director-rail-icon"><Icon size={15} /></span><span>{label}</span>{done ? <Check size={14} className="is-done" /> : null}</button>)}
          <div className="director-rail-divider" /><div className="director-rail-note"><span className="director-pulse" /> 方案已就绪<br /><small>4 个镜头 · 18 秒 · 16:9</small></div>
        </aside>
        <main className="director-mockup-main">
          <div className="director-mockup-heading"><div><span className="director-kicker">镜头制作</span><h1>把方案变成一段可以观看的故事</h1><p>逐镜确认画面、人物与动作；每个镜头都可以独立重做。</p></div><Button icon={<Plus size={15} />}>添加镜头</Button></div>
          {view === "方案" ? <>
            <section className="director-mockup-preview"><div className={`director-mockup-poster tone-${current.tone}`}><div className="poster-grid" /><div className="poster-light" /><span className="poster-caption">SHOT {current.id}</span><div className="poster-subject"><div className="poster-head" /><div className="poster-body" /></div><span className="poster-location">PLATFORM 03 · 23:41</span></div><div className="director-preview-copy"><div className="director-preview-top"><Tag color="processing">{current.status}</Tag><span>{current.meta}</span></div><h2>{current.title}</h2><p>中近景 · 缓慢推近 · 环境声：远处列车与雨声</p><div className="director-preview-progress"><span style={{ width: current.status === "生成中" ? "62%" : current.status === "已完成" ? "100%" : "0%" }} /></div><div className="director-preview-bottom"><Button type="text" icon={<ChevronLeft size={16} />} /><Button type="primary" shape="circle" icon={<Play size={16} />} /><Button type="text" icon={<ChevronRight size={16} />} /><span>预览片段</span></div></div></section>
            <section className="director-shot-list"><div className="director-list-head"><strong>镜头轨</strong><span>4 个镜头 · 18 秒</span><button type="button">排序</button></div><div className="director-shot-row">{shots.map((shot) => <button type="button" key={shot.id} onClick={() => setSelected(shot.id)} className={`director-shot ${selected === shot.id ? "is-selected" : ""}`}><div className={`director-shot-thumb tone-${shot.tone}`}><span>{shot.id}</span>{shot.status === "生成中" ? <span className="director-shot-loading" /> : null}</div><div className="director-shot-info"><strong>{shot.title}</strong><span>{shot.meta}</span></div><Tag bordered={false} color={shot.status === "已完成" ? "success" : shot.status === "生成中" ? "processing" : "default"}>{shot.status}</Tag></button>)}</div></section>
          </> : <section className="director-edit-view"><div className="director-edit-strip">{shots.map((shot) => <div className={`director-edit-thumb tone-${shot.tone} ${selected === shot.id ? "is-selected" : ""}`} key={shot.id} onClick={() => setSelected(shot.id)}>{shot.id}</div>)}</div><div className="director-edit-empty"><Play size={24} /><strong>剪辑视图预览</strong><span>把镜头拖入时间轴，调整节奏与衔接。</span></div></section>}
        </main>
        <aside className="director-mockup-inspector"><div className="director-inspector-head"><div><span>当前镜头</span><strong>SHOT {current.id}</strong></div><Button type="text" icon={<MoreHorizontal size={18} />} /></div><div className="director-inspector-section"><label>镜头描述</label><p>{current.title}。人物站在站台边缘，雨水从玻璃上滑落，远处灯光虚化。</p></div><div className="director-inspector-section"><label>画面参数</label><div className="director-inspector-grid"><span>景别<b>中近景</b></span><span>机位<b>平视</b></span><span>运镜<b>缓慢推近</b></span><span>时长<b>5 秒</b></span></div></div><div className="director-inspector-section"><label>参考内容</label><div className="director-reference-list"><div className="director-reference"><Image size={15} /><span>人物 · 林夏</span><Check size={14} /></div><div className="director-reference"><Image size={15} /><span>场景 · 3号站台</span><Check size={14} /></div></div></div><div className="director-inspector-foot"><Button block icon={<Wand2 size={15} />}>重新生成这个镜头</Button><small>预计消耗 1 次视频生成</small></div></aside>
      </div>
    </div>
  )
}
