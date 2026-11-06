import { useEffect, useState } from "react"
import { Button, ColorPicker, Radio, Select, Tabs, Tooltip } from "antd"
import { Modal } from "antd"
import { RotateCcw, UserRound, Layers } from "lucide-react"
import catalog from "../../character-design-presets.json"
import type { CharacterDesign } from "../../asset-canvas-creative"
import "./character-design.css"

const skinColors = ["#e5e5e2", "#fff6e6", "#f6d6a8", "#dfaa6c", "#824c30", "#493023"]
const hairColors = ["#22201f", "#574032", "#a97d46", "#e9d6ac", "#a9a5a3", "#ede8e5"]
const regions: Record<string, string[]> = {
  "东亚": ["中国", "日本", "韩国", "蒙古"], "东南亚": ["泰国", "越南", "马来西亚", "印度尼西亚", "菲律宾"],
  "南亚": ["印度", "巴基斯坦", "孟加拉国", "斯里兰卡", "尼泊尔"], "西亚 / 北非": ["西亚", "北非"],
  "欧洲": ["西欧", "北欧", "南欧", "东欧"], "撒哈拉以南非洲": ["西非", "东非", "中非", "南部非洲", "非洲之角", "其他撒哈拉以南非洲"],
  "拉丁美洲": ["中美洲", "南美洲", "加勒比地区"], "北美 / 大洋洲": ["北美", "澳大利亚", "新西兰", "太平洋岛屿"],
}

export default function CharacterDesignModal({ open, value, onCancel, onSave }: { open: boolean; value: CharacterDesign; onCancel: () => void; onSave: (value: CharacterDesign) => void | Promise<void> }) {
  const [draft, setDraft] = useState<CharacterDesign>({})
  const [tab, setTab] = useState("basic")
  const [saving, setSaving] = useState(false)
  useEffect(() => { if (open) { setDraft({ ...value }); setTab("basic") } }, [open])
  const change = (label: string, next: string) => setDraft(previous => { const result = { ...previous, [label]: next }; if (label === "区域 / 文化背景") delete result["地区细分（可选）"]; return result })
  return <Modal title="角色设计" open={open} width={840} centered className="ac-character-design" classNames={{ wrapper: "ac-design-mask" }} onCancel={onCancel} destroyOnHidden footer={<><Button disabled={saving} onClick={onCancel}>取消</Button><Button className="ac-monochrome" loading={saving} onClick={async () => { setSaving(true); try { await onSave(draft) } finally { setSaving(false) } }}>保存</Button></>}>
    <div className="ac-design-tabs"><Tabs activeKey={tab} onChange={setTab} items={catalog.map(item => ({ key: item.id, label: <span>{item.id === "style" ? <Layers size={13}/> : <UserRound size={13}/>} {item.label}</span> }))}/><Tooltip title="重置全部角色设计"><Button type="text" aria-label="重置角色设计" icon={<RotateCcw size={16}/>} onClick={() => setDraft({})}/></Tooltip></div>
    <div className="ac-design-content" key={tab}>
      {catalog.find(item => item.id === tab)?.groups.map(group => {
        const isColor = ["肤色", "发色"].includes(group.label)
        const options = [...new Set(group.options)]
        return <div className="ac-design-row" key={group.label}><label className={group.label === "区域 / 文化背景" || group.label.includes("（可选）") ? "is-two-line" : undefined}>{group.label === "区域 / 文化背景" ? "区域 / 文化\n背景" : group.label.includes("（可选）") ? group.label.replace("（可选）", "\n（可选）") : group.label}</label><div>{group.control === "region_select" ? <Select variant="filled" aria-label="地区细分" disabled={!draft["区域 / 文化背景"]} placeholder={draft["区域 / 文化背景"] ? "不特别指定" : "请先选择大区"} value={draft[group.label] || undefined} onChange={value => change(group.label, value || "")} allowClear showSearch optionFilterProp="label" options={["不特别指定", ...(regions[draft["区域 / 文化背景"]] || [])].map(label => ({ label, value: label === "不特别指定" ? "" : label }))}/> : <>
          <Radio.Group className={`ac-design-choices${isColor ? " is-colors" : ""}`} aria-label={group.label} value={draft[group.label]} onChange={event => change(group.label, event.target.value)}>
            {options.filter(item => item !== "自定义").map((label, i) => <Radio.Button key={label} value={label} onClick={() => { if (draft[group.label] === label) change(group.label, "") }} title={label}>{isColor ? <span className="ac-design-swatch" style={{ background: (group.label === "肤色" ? skinColors : hairColors)[i] || label }}/>: label}</Radio.Button>)}
          </Radio.Group>{isColor && <ColorPicker value={draft[group.label]?.startsWith("#") ? draft[group.label] : "#c8a581"} onChangeComplete={color => change(group.label, color.toHexString())}><Button className={draft[group.label]?.startsWith("#") ? "is-selected" : ""}>自定义</Button></ColorPicker>}
        </>}</div></div>
      })}
    </div>
  </Modal>
}
