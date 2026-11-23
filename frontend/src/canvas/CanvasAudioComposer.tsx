import { useReactFlow } from "@xyflow/react"
import { Button, Dropdown, Input, Select, Tooltip } from "antd"
import { ArrowUp, AudioLines, Check, ChevronDown, LoaderCircle, Maximize2, Minimize2, Music, TriangleAlert, Type } from "lucide-react"
import { useEffect, useState, type KeyboardEvent } from "react"
import { isSubmitEnter } from "../lib/enter-submit"
import {
  CANVAS_MUSIC_DURATIONS, canvasAudioModeLabel, canvasAudioProviderLabel, canvasMusicDurationLabel,
  fetchCanvasAudioOptions, type CanvasAudioMode, type CanvasAudioOptions,
} from "./canvas-audio"
import { canvasJobStatusLabel, generatorPromptIssue, isCanvasJobActive, type CanvasGeneratorPromptState } from "./canvas-generation"
import type { CanvasNode } from "./canvas-model"
import type { CanvasNodeActions } from "./node-primitives"
import { useCanvasTextDraft } from "./useCanvasTextDraft"

export function CanvasAudioComposer({ id, data, actions, prompt, disconnectPrompt }: {
  id: string
  data: CanvasNode["data"]
  actions: CanvasNodeActions
  prompt: CanvasGeneratorPromptState
  disconnectPrompt: () => void
}) {
  const { updateNodeData } = useReactFlow<CanvasNode>()
  const [options, setOptions] = useState<CanvasAudioOptions | null>(null)
  const [optionsError, setOptionsError] = useState("")
  const [reload, setReload] = useState(0)
  const [expanded, setExpanded] = useState(false)
  const textDraft = useCanvasTextDraft(prompt.fromTextNodes ? prompt.text : data.text ?? "",
    (value) => updateNodeData(id, { text: value }))
  const mode: CanvasAudioMode = data.audioMode === "music" ? "music" : "tts"
  const active = isCanvasJobActive(data.jobStatus)
  const text = textDraft.value
  const maxLength = mode === "music" ? 1000 : 1200
  const voices = options?.tts.voices ?? []
  const voice = data.voice || options?.tts.voice || voices[0]?.id || undefined
  const configured = mode === "music" ? options?.music.configured : options?.tts.configured
  const promptIssue = prompt.fromTextNodes ? generatorPromptIssue(text, prompt) : null
  const canSubmit = !promptIssue && Boolean(text.trim()) && text.length <= maxLength && Boolean(configured) && !active
  const issue = optionsError || promptIssue || (options && !configured
    ? mode === "music" ? "请先在管理设置中配置音乐生成服务" : options.tts.reason || "请先在管理设置中配置语音服务"
    : text.length > maxLength ? `内容最多 ${maxLength} 字，请缩短后生成` : "")
  const error = !active ? String(data.jobError ?? "") : ""

  useEffect(() => {
    const controller = new AbortController()
    setOptionsError("")
    fetchCanvasAudioOptions(controller.signal).then(setOptions).catch((error: unknown) => {
      if (!controller.signal.aborted) setOptionsError(error instanceof Error ? error.message : "音色目录读取失败")
    })
    return () => controller.abort()
  }, [reload])

  const containKeys = (event: KeyboardEvent<HTMLElement>) => {
    if (event.ctrlKey || event.metaKey) {
      if (event.key.toLowerCase() === "s") {
        event.preventDefault()
        actions.saveCanvas()
      }
      if (event.key === "Enter" && !event.nativeEvent.isComposing) {
        event.preventDefault()
        if (canSubmit) actions.generateAudio(id)
      }
    }
    event.stopPropagation()
  }

  return (
    <section className={`canvas-creative-panel canvas-audio-composer nodrag nopan nowheel${expanded ? " is-expanded" : ""}`}
      aria-label="音频创作区" aria-busy={active} onKeyDown={containKeys}
      onPointerDown={(event) => event.stopPropagation()} onDoubleClick={(event) => event.stopPropagation()}>
      <Tooltip title={expanded ? "收起输入区" : "展开输入区"}>
        <Button type="text" className="canvas-audio-expand" size="small" aria-label={expanded ? "收起输入区" : "展开输入区"}
          aria-expanded={expanded} icon={expanded ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
          onClick={() => setExpanded((value) => !value)} />
      </Tooltip>
      {prompt.fromTextNodes ? (
        <div className="canvas-composer-text-source"><Type size={12} />来自 {prompt.connectedTextNodes} 个文字节点
          <Button type="text" size="small" disabled={active} onClick={disconnectPrompt}>断开</Button>
        </div>
      ) : null}
      <Input.TextArea className="canvas-audio-input" id={`canvas-audio-${id}`} name={`canvas-audio-${id}`}
        aria-label={mode === "music" ? "音乐描述" : "说话内容"} variant="borderless" value={text} disabled={active} readOnly={prompt.fromTextNodes}
        placeholder={mode === "music" ? "描述你想要的音乐，例如：温暖的钢琴前奏，适合片尾" : "请输入你想生成的说话内容"}
        autoSize={{ minRows: expanded ? 9 : 4, maxRows: expanded ? 12 : 6 }} maxLength={maxLength}
        onFocus={textDraft.onFocus} onBlur={textDraft.onBlur}
        onCompositionStart={textDraft.onCompositionStart}
        onCompositionEnd={(event) => textDraft.onCompositionEnd(event.currentTarget.value)}
        onChange={(event) => textDraft.onChange(event.target.value)}
        onKeyDown={(event) => {
          // 回车直接生成；与 Ctrl / ⌘ + Enter 行为一致。
          if (!isSubmitEnter(event)) return
          event.preventDefault()
          if (canSubmit) actions.generateAudio(id)
        }} />
      {issue || error ? <div className="canvas-audio-feedback" role="status">
        <TriangleAlert size={13} /><span>{error || issue}</span>
        {optionsError ? <Button type="link" size="small" onClick={() => setReload((value) => value + 1)}>重新加载</Button> : null}
      </div> : null}
      <div className="canvas-audio-controls">
        <Dropdown trigger={["click"]} placement="topLeft" disabled={active}
          classNames={{ root: "canvas-popup canvas-audio-mode-menu" }} menu={{
            selectable: true, selectedKeys: [mode],
            items: (["tts", "music"] as const).map((item) => ({
              key: item, icon: item === "music" ? <Music size={16} /> : <AudioLines size={16} />,
              label: <span className="canvas-audio-mode-option">{canvasAudioModeLabel(item)}{mode === item ? <Check size={16} /> : null}</span>,
            })),
            onClick: ({ key }) => {
              if (key === mode) return
              updateNodeData(id, { audioMode: key === "music" ? "music" : "tts", jobId: null, jobStatus: null, jobProgress: null, jobError: null, resultUrl: null })
            },
          }}>
          <Button type="text" className="canvas-audio-mode" aria-label="生成方式" aria-haspopup="menu" disabled={active}>
            {mode === "music" ? <Music size={15} /> : <AudioLines size={15} />}
            {canvasAudioModeLabel(mode)}<ChevronDown size={12} />
          </Button>
        </Dropdown>
        <span className="canvas-audio-provider">{mode === "music" ? "本地音乐" : canvasAudioProviderLabel(options?.tts.provider)}</span>
        {mode === "tts" ? <Select size="small" variant="borderless" className="canvas-audio-select" aria-label="音色"
          placement="topLeft" classNames={{ popup: { root: "canvas-select-popup canvas-audio-voice-menu" } }}
          value={voice} placeholder={options ? "默认音色" : "加载音色…"} loading={!options && !optionsError}
          options={voices.map((item) => ({ value: item.id, label: item.label }))} disabled={active || !voices.length}
          popupMatchSelectWidth={240} onChange={(value) => updateNodeData(id, { voice: value })} />
          : <Select size="small" variant="borderless" className="canvas-audio-select" aria-label="音乐时长"
            placement="topLeft" classNames={{ popup: { root: "canvas-select-popup" } }} value={data.durationSeconds ?? 60}
            options={CANVAS_MUSIC_DURATIONS.map((value) => ({ value, label: canvasMusicDurationLabel(value) }))}
            disabled={active} popupMatchSelectWidth={false} onChange={(value) => updateNodeData(id, { durationSeconds: value })} />}
        <div className="canvas-audio-submit-area">
          <span className="canvas-audio-output-count">{active ? canvasJobStatusLabel(String(data.jobStatus)) : "1 段"}</span>
          <Tooltip title={active ? "正在生成" : issue || (text.trim() ? "生成 · Enter" : "先输入内容")}>
            <Button className="canvas-audio-submit" type="text" shape="circle" aria-label={mode === "music" ? "生成音乐" : "生成音频"}
              disabled={!canSubmit} icon={active ? <LoaderCircle className="canvas-spin" size={18} /> : <ArrowUp size={20} />}
              onClick={() => actions.generateAudio(id)} />
          </Tooltip>
        </div>
      </div>
    </section>
  )
}
