import { Button, Collapse, Drawer, Select, Space, Switch } from "antd"
import { useState } from "react"
import type { RecipeProject } from "../recipe-model"
import type { DirectorControl } from "../director-workflows"

export default function DirectorProductionSettings({ recipe, controls, families, family, mode, mobile, polish, onMode, onPolish, onChange }: {
  recipe: RecipeProject; controls: DirectorControl[]; families: Array<{ value: string; label: string }>; family: string
  mode: "still" | "preview" | "final" | "custom"; mobile: boolean; polish: boolean
  onMode: (mode: "still" | "preview" | "final" | "custom") => void; onPolish: (value: boolean) => void
  onChange: (patch: Partial<RecipeProject>) => void
}) {
  const [open, setOpen] = useState(false)
  const values = recipe as unknown as Record<string, unknown>
  const renderControl = (control: DirectorControl) => {
    const preview = mode === "preview" && control.preview_field
    const storedValue = String(values[preview || control.field] ?? control.default)
    const value = preview && !control.options.some((item) => item.value === storedValue) ? control.default : storedValue
    const choices = control.options.some((item) => item.value === value) ? control.options : [...control.options, { value, label: `${value}（已有设置）` }]
    return <label className="director-setting-field" key={control.field}><span>{control.label}</span><Select aria-label={control.label} value={value} options={choices} disabled={Boolean(preview)} onChange={(next) => onChange({ [control.field]: next })} /></label>
  }
  const content = <div className="director-production-form">
    <label className="director-setting-field"><span>视频工作流</span><Select aria-label="视频工作流" value={family} options={families} onChange={(value) => onChange({ videoWorkflowFamily: value })} /></label>
    <label className="director-setting-field"><span>生成目标</span><Select aria-label="生成目标" value={mode} options={[{ value: "still", label: "静帧" }, { value: "preview", label: "预览" }, { value: "final", label: "终稿" }, ...(mode === "custom" ? [{ value: "custom", label: "已有自定义设置" }] : [])]} onChange={onMode} /></label>
    {controls.filter((item) => item.ui_group === "primary").map(renderControl)}
    {!controls.length ? <p>当前工作流使用已有设置；参数目录加载后可调整。</p> : null}
    <Collapse items={[{ key: "advanced", label: "更多设置", children: <Space direction="vertical" className="w-full">{controls.filter((item) => item.ui_group === "advanced").map(renderControl)}<label className="director-setting-field"><span>生成前润色提示词</span><Switch aria-label="生成前润色提示词" checked={polish} onChange={onPolish} disabled={mode === "still"} /></label></Space> }]} />
  </div>
  const summary = `生成设置 · ${recipe.aspectRatio} · ${mode === "still" ? "静帧" : mode === "preview" ? "预览" : "终稿"}`
  return mobile ? <><Button className="director-settings-entry" onClick={() => setOpen(true)}>{summary}</Button><Drawer title="生成设置" open={open} onClose={() => setOpen(false)} size="100%">{content}</Drawer></>
    : <Collapse className="director-production-settings" items={[{ key: "settings", label: summary, children: content }]} />
}
