import { Alert, Button, Collapse, Form, Input, InputNumber, Segmented, Select, message } from "antd"
import type { TextAreaRef } from "antd/es/input/TextArea"
import { ArrowUpRight } from "lucide-react"
import { useRef, useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { MusicJobCreatePayload, adapterLabel, createMusicJob, fetchMusicConfig } from "./api"

const GENRES = [{ label: "流行", tag: "pop" }, { label: "民谣", tag: "folk" }, { label: "摇滚", tag: "rock" }, { label: "电子", tag: "electronic" }, { label: "古风", tag: "Chinese traditional" }, { label: "爵士", tag: "jazz" }, { label: "嘻哈", tag: "hip-hop" }, { label: "氛围", tag: "ambient" }]
const SECTIONS = [{ label: "主歌", tag: "[Verse 1]" }, { label: "副歌前奏", tag: "[Pre-Chorus]" }, { label: "副歌", tag: "[Chorus]" }, { label: "桥段", tag: "[Bridge]" }, { label: "尾声", tag: "[Outro]" }]
const DURATIONS = [{ label: "30秒", value: 30 }, { label: "1分钟", value: 60 }, { label: "3分钟", value: 180 }, { label: "3.5分钟", value: 210 }]
type FormValues = { title?: string; style: string; lyrics?: string; duration_seconds: number; output_format: string; adapters?: string[] }

export default function MusicCreateForm({ csrfToken, disabled }: { csrfToken: string; disabled?: boolean }) {
  const [form] = Form.useForm<FormValues>()
  const [submitting, setSubmitting] = useState(false)
  const queryClient = useQueryClient()
  const lyricsRef = useRef<TextAreaRef>(null)
  const duration = Form.useWatch("duration_seconds", form) ?? 180
  const configQuery = useQuery({ queryKey: ["music-config"], queryFn: fetchMusicConfig, staleTime: 5 * 60 * 1000, retry: false })
  const adapters = configQuery.data?.adapters ?? []
  const addGenre = (tag: string) => {
    const current = String(form.getFieldValue("style") || "").trim()
    if (!current.split(/[,，]/).some((part) => part.trim().toLowerCase() === tag.toLowerCase())) form.setFieldValue("style", current ? `${current}, ${tag}` : tag)
  }
  const insertSection = (tag: string) => {
    const current = String(form.getFieldValue("lyrics") || "")
    const el = lyricsRef.current?.resizableTextArea?.textArea
    const start = el?.selectionStart ?? current.length
    const end = el?.selectionEnd ?? start
    const prefix = start && current[start - 1] !== "\n" ? "\n" : ""
    const inserted = `${prefix}${tag}\n`
    form.setFieldValue("lyrics", `${current.slice(0, start)}${inserted}${current.slice(end)}`)
    requestAnimationFrame(() => { if (el) { el.focus(); el.setSelectionRange(start + inserted.length, start + inserted.length) } })
  }
  const submit = async (values: FormValues) => {
    setSubmitting(true)
    const payload: MusicJobCreatePayload = {
      title: values.title?.trim() || "", style: values.style.trim(), lyrics: values.lyrics?.trim() || "",
      duration_seconds: values.duration_seconds, output_format: values.output_format, cot: "full",
      adapters: (values.adapters || []).map((id) => ({ id })),
    }
    try {
      await createMusicJob(csrfToken, payload)
      message.success("音乐已提交，正在为你创作")
      form.resetFields(["title", "lyrics"])
      await queryClient.invalidateQueries({ queryKey: ["music-jobs"] })
    } catch (error) { message.error(error instanceof Error ? error.message : "音乐任务提交失败") }
    finally { setSubmitting(false) }
  }

  return <Form form={form} layout="vertical" requiredMark={false} initialValues={{ duration_seconds: 180, output_format: "flac" }} onFinish={submit} className="studio-music-form" disabled={disabled || submitting}>
    <div className="studio-music-advanced-grid">
      <div>
        <Form.Item name="title" label="歌曲标题" rules={[{ max: 120, message: "标题不能超过120字" }]}><Input placeholder="给这首歌起个名字，也可以留空" allowClear /></Form.Item>
        <Form.Item name="style" label="音乐风格" rules={[{ required: true, whitespace: true, message: "请描述音乐风格" }, { max: 2000, message: "风格不能超过2000字" }]} extra="建议用英文描述曲风、人声、乐器与情绪。"><Input.TextArea rows={3} placeholder="warm acoustic folk, male vocal, acoustic guitar, hopeful, 82 BPM" /></Form.Item>
        <div className="studio-music-chips" aria-label="风格灵感">{GENRES.map((genre) => <Button size="small" key={genre.tag} onClick={() => addGenre(genre.tag)}>{genre.label}</Button>)}</div>
        <span className="studio-music-label">音乐时长</span>
        <Segmented className="studio-music-form-duration" block value={duration} options={DURATIONS} onChange={(value) => form.setFieldValue("duration_seconds", value)} />
        <div className="studio-music-form-row">
          <Form.Item name="duration_seconds" label="自定义时长" rules={[{ required: true, type: "number", min: 10, max: 600, message: "时长应为10至600秒" }]}><InputNumber min={10} max={600} precision={0} suffix="秒" style={{ width: "100%" }} /></Form.Item>
          <Form.Item name="output_format" label="输出格式"><Select options={[{ value: "flac", label: "FLAC · 无损" }, { value: "mp3", label: "MP3 · 轻巧" }, { value: "wav", label: "WAV · 无损" }]} /></Form.Item>
        </div>
      </div>
      <div>
        <Form.Item name="lyrics" label="歌词" rules={[{ max: 8000, message: "歌词不能超过8000字" }]} extra="按段落写下歌词，留空即生成纯音乐。"><Input.TextArea ref={lyricsRef} rows={11} placeholder={"[Verse 1]\n晨光落在我的窗台\n\n[Chorus]\n让旋律越过山海"} /></Form.Item>
        <div className="studio-music-chips" aria-label="歌词段落">{SECTIONS.map((section) => <Button size="small" key={section.tag} onClick={() => insertSection(section.tag)}>{section.label}</Button>)}</div>
      </div>
    </div>
    {adapters.length > 0 && <Collapse ghost size="small" className="studio-music-advanced" items={[{ key: "presets", label: "更多风格预设", children: <Form.Item name="adapters" label="风格预设"><Select mode="multiple" allowClear showSearch={{ optionFilterProp: ["label", "value"] }} placeholder="可选，叠加你喜欢的音乐风格" options={adapters.map((adapter) => ({ value: adapter.id, label: adapterLabel(adapter) }))} /></Form.Item> }]} />}
    {configQuery.data?.error && <Alert type="warning" showIcon title="风格预设暂不可用，仍可直接生成音乐" />}
    <div className="studio-music-advanced-footer"><span>写好歌词，让旋律接着讲述。</span><Button type="primary" htmlType="submit" loading={submitting} className="studio-music-send">生成音乐 <ArrowUpRight size={19} /></Button></div>
  </Form>
}
