import { Button, Dropdown, Input, Popover, Radio, Segmented, Select, Tooltip } from "antd"
import { AtSign, AudioLines, ChevronDown, ChevronUp, History, Image as ImageIcon, Scan, SlidersHorizontal, Sparkles, Video, X } from "lucide-react"
import { useState, type KeyboardEvent } from "react"
import { isSubmitEnter } from "../lib/enter-submit"
import { searchFilterOption } from "../search-match"
import { CanvasCreditEstimate } from "./CanvasCreditEstimate"
import type { CanvasNodeActions } from "./node-primitives"
import { GeneratorOptionField } from "./CanvasGeneratorInspector"
import { canvasComposerOptionChoices, canvasComposerOptionLabel, canvasComposerParameterLayout, canvasReferenceSlots } from "./canvas-composer"
import { parseCanvasFrameRatio } from "./canvas-frame"
import {
  canvasModeAcceptsReferenceKind, canvasPictureToken, canvasReferenceKind, canvasReferenceLabel, canvasReferencePreviewUrl, canvasReferenceUrl,
  defaultGeneratorOptionValues, generatorOptionValues, generatorParameterSummary, validateGeneratorInput,
  type CanvasOptionValue, type CanvasReferenceKind, type CanvasWorkflowMode,
} from "./canvas-generation"
import type { CanvasNode, CanvasRunSnapshot } from "./canvas-model"

export type CanvasResultRunState = {
  prompt: string
  workflowId: string
  optionValues: Record<string, CanvasOptionValue>
  includeSelf: boolean
}

/**
 * 选中图片/视频结果节点时的底部参数回显栏（对齐即梦交互）：
 * 回显上次生成的提示词与参数，调整后一键基于当前结果再次生成。
 * 提交时新建生成节点（当前结果自动接为参考素材），复用既有提交与进度体系。
 */
export function CanvasResultComposer({ node, provenance, modes, modesLoading, actions, onRun, authenticated = true }: {
  node: CanvasNode
  provenance: CanvasRunSnapshot
  modes: CanvasWorkflowMode[]
  modesLoading: boolean
  actions: CanvasNodeActions
  onRun: (state: CanvasResultRunState, options: { submit?: boolean; referenceKind?: CanvasReferenceKind | null }) => void
  authenticated?: boolean
}) {
  const [workflowId, setWorkflowId] = useState(() => (
    modes.some((mode) => mode.id === provenance.workflowId) ? provenance.workflowId : ""
  ))
  const [prompt, setPrompt] = useState(provenance.prompt)
  const [storedValues, setStoredValues] = useState<Record<string, CanvasOptionValue>>(() => provenance.optionValues)
  const [includeSelf, setIncludeSelf] = useState(true)
  const [parametersOpen, setParametersOpen] = useState(false)
  const [advancedOpen, setAdvancedOpen] = useState(false)

  const mode = modes.find((item) => item.id === workflowId) ?? null
  const isImage = mode?.media_type === "image"
  const values = generatorOptionValues(mode, storedValues)
  const fields = canvasComposerParameterLayout(mode, values)
  const settingsFields = [...fields.visual.flatMap(({ field, companions }) => [field, ...companions]), ...fields.primary]
  const summary = generatorParameterSummary(mode, values)
  const compactSummary = settingsFields.filter(([, definition]) => definition.type !== "boolean").slice(0, 3)
    .map(([name, definition]) => canvasComposerOptionLabel(definition, values[name])).filter(Boolean)
  const selfKind: CanvasReferenceKind = node.type === "video" ? "video" : "image"
  const selfAccepted = mode ? canvasModeAcceptsReferenceKind(mode, selfKind) : false
  const references = includeSelf && selfAccepted ? [node] : []
  const issue = validateGeneratorInput(mode, prompt, references, null)
  const slots = canvasReferenceSlots(mode, references)
  const showsSlotLabels = mode?.reference_mode === "keyframes" || slots.some(({ kind }) => kind !== "image")
  const pictures = references.filter((reference) => canvasReferenceKind(reference) === "image")

  const runState = (): CanvasResultRunState => ({ prompt, workflowId, optionValues: values, includeSelf })

  const containKeys = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") { setParametersOpen(false); setAdvancedOpen(false) }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
      event.preventDefault()
      actions.saveCanvas()
    }
    event.stopPropagation()
  }

  const changeWorkflow = (value: string) => {
    setParametersOpen(false)
    setAdvancedOpen(false)
    setWorkflowId(value)
    setStoredValues(defaultGeneratorOptionValues(modes.find((item) => item.id === value) ?? null))
  }

  const parameterContent = (advanced: boolean) => (
    <div className="canvas-workflow-option-fields nodrag nopan nowheel" onKeyDown={containKeys}>
      {(advanced ? fields.advanced : settingsFields).map(([name, definition]) => {
        const choices = canvasComposerOptionChoices(definition)
        const visual = definition.ui_control === "visual-settings"
        const maxLabelLength = Math.max(1, ...choices.map((choice) => (choice.short_label || choice.label).length))
        const segmented = !visual && (choices.length <= 4 || (choices.length <= 8 && maxLabelLength <= 16))
        const columns = choices.length ? visual ? Math.ceil(choices.length / Math.ceil(choices.length / 9))
          : Math.min(choices.length, maxLabelLength > 16 ? 2 : maxLabelLength > 8 ? 3 : 6) : 1
        const setChoice = (raw: string | number) => {
          const choice = choices.find((item) => String(item.value) === String(raw))
          if (choice) setStoredValues((current) => ({ ...generatorOptionValues(mode, current), [name]: choice.value }))
        }
        return choices.length && definition.type !== "boolean" ? (
          <fieldset key={name} className="canvas-workflow-setting-field">
            <legend>{definition.label}{definition.unit ? `（${definition.unit}）` : ""}</legend>
            {!segmented ? (
              <Radio.Group className={`canvas-setting-choices${visual ? " is-ratio" : ""}`} aria-label={definition.label} name={`canvas-result-option-${node.id}-${name}`}
                style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }} value={String(values[name] ?? definition.default)}
                onChange={(event) => setChoice(event.target.value)}>
                {choices.map((choice) => {
                  const ratio = parseCanvasFrameRatio(choice.value)
                  return <Radio.Button key={choice.value} value={String(choice.value)} title={choice.hint || choice.label}>
                    <span className="canvas-setting-choice-label">
                      {visual ? <span className="canvas-setting-ratio-symbol" aria-hidden="true">{ratio
                        ? <span className="canvas-setting-ratio-outline" style={{ width: ratio >= 1 ? 14 : Math.max(5, 14 * ratio), height: ratio >= 1 ? Math.max(5, 14 / ratio) : 14 }} />
                        : <Scan size={14} />}</span> : null}
                      <span>{visual ? canvasComposerOptionLabel(definition, choice.value) : choice.short_label || choice.label}</span>
                      {!visual && choice.short_label && choice.hint ? <small>{choice.hint}</small> : null}
                    </span>
                  </Radio.Button>
                })}
              </Radio.Group>
            ) : (
              <Segmented block className="canvas-setting-segments" aria-label={definition.label} name={`canvas-result-option-${node.id}-${name}`}
                value={String(values[name] ?? definition.default)}
                options={choices.map((choice) => ({ value: String(choice.value), title: choice.label,
                  label: <span className="canvas-setting-choice-label"><span>{choice.short_label || choice.label}</span>{choice.short_label && choice.hint ? <small>{choice.hint}</small> : null}</span>,
                }))} onChange={setChoice} />
            )}
            {definition.description ? <p className="canvas-setting-hint">{definition.description}</p> : null}
          </fieldset>
        ) : <GeneratorOptionField key={name} name={name} definition={definition} value={values[name]} disabled={false} onChange={(fieldName, next) => setStoredValues((current) => ({ ...generatorOptionValues(mode, current), [fieldName]: next }))} />
      })}
    </div>
  )

  const echoTime = provenance.submittedAt > 0
    ? new Date(provenance.submittedAt).toLocaleTimeString("zh-CN", { hour12: false, hour: "2-digit", minute: "2-digit" })
    : ""

  return (
    <section className="canvas-creative-panel canvas-generator-composer canvas-result-composer nodrag nopan nowheel" aria-label="结果节点创作区"
      onPointerDown={(event) => event.stopPropagation()} onDoubleClick={(event) => event.stopPropagation()}
      onKeyDown={containKeys}>
      <div className="canvas-result-echo" role="note">
        <History size={12} />
        <span title={provenance.parameterSummary.join(" · ")}>
          回显上次参数{provenance.workflowName ? ` · ${provenance.workflowName}` : ""}{echoTime ? ` · ${echoTime}` : ""}
        </span>
      </div>
      {slots.length ? (
        <div className="canvas-composer-references" aria-label="参考素材">
          {slots.map(({ index, node: slotNode, kind, required, label }) => {
            // 回显栏的参考素材只可能是当前结果节点本身或待添加的空槽位。
            const isSelf = slotNode?.id === node.id
            const url = isSelf ? canvasReferenceUrl(node, kind) : null
            const thumbnail = kind === "image" ? isSelf ? canvasReferencePreviewUrl(node, kind) : null : kind === "video" ? node.data.cover : null
            const requirement = required ? "（必填）" : "（可选）"
            if (isSelf) {
              return (
                <div className="canvas-composer-reference is-filled" key={`self-${node.id}`}>
                  <Tooltip title={`以当前${kind === "video" ? "视频" : "图片"}为底再次生成${url ? "" : " · 素材待就绪"}`}>
                    <Button type="text" className="canvas-composer-reference-preview" aria-label={`当前${kind === "video" ? "视频" : "图片"}作为参考`}>
                      {thumbnail ? <img src={thumbnail} alt={label} draggable={false} /> : kind === "video" ? <Video size={19} /> : <ImageIcon size={19} />}
                      <span className="canvas-composer-reference-number">{index + 1}</span>
                      {showsSlotLabels ? <span className="canvas-composer-reference-label">{label}</span> : null}
                    </Button>
                  </Tooltip>
                  <Button type="text" size="small" className="canvas-composer-reference-remove" icon={<X size={10} />}
                    aria-label="移除当前结果参考" onClick={() => setIncludeSelf(false)} />
                </div>
              )
            }
            return (
              <div className="canvas-composer-reference" key={`slot-${index}`}>
                <Tooltip title={`添加${label}${requirement} · 将按当前参数新建生成节点`}>
                  <Button type="text" className="canvas-composer-reference-preview" aria-label={`添加${label}${requirement}`}
                    onClick={() => onRun(runState(), { submit: false, referenceKind: kind })}>
                    {kind === "video" ? <Video size={19} /> : kind === "audio" ? <AudioLines size={19} /> : <ImageIcon size={19} />}
                    {showsSlotLabels ? <span className="canvas-composer-reference-label">{label}{required ? " *" : mode?.reference_mode === "keyframes" ? " · 可选" : ""}</span> : null}
                  </Button>
                </Tooltip>
              </div>
            )
          })}
        </div>
      ) : null}
      <Input.TextArea aria-label="再次生成提示词" className="canvas-composer-prompt" value={prompt} variant="borderless"
        autoSize={{ minRows: 2, maxRows: 5 }} maxLength={4000}
        placeholder={mode?.media_type === "video" ? "描述画面、镜头与动作…" : "描述你想生成的画面…"}
        onChange={(event) => setPrompt(event.target.value)}
        onKeyDown={(event) => {
          // 回车直接按当前参数新建生成节点并开始生成。
          if (!isSubmitEnter(event)) return
          event.preventDefault()
          if (!issue && mode && !modesLoading) onRun(runState(), { submit: true })
        }} />
      {issue ? <div className="canvas-composer-validation" role="status">{issue}</div> : null}
      <div className="canvas-composer-controls">
        <Select aria-label="再次生成工作流" className="canvas-composer-workflow" size="small" placement="topLeft"
          variant="borderless"
          classNames={{ popup: { root: "canvas-select-popup" } }} popupMatchSelectWidth={280}
          value={workflowId || undefined} placeholder={provenance.workflowName || "选择工作流"} loading={modesLoading}
          disabled={modesLoading} showSearch filterOption={searchFilterOption}
          options={modes.map((item) => ({ value: item.id, label: item.name }))}
          onChange={changeWorkflow} />
        {fields.primary.length || fields.visual.length ? (
          <Popover trigger="click" placement="topLeft" arrow={false} open={parametersOpen}
            onOpenChange={(open) => { setParametersOpen(open); if (open) setAdvancedOpen(false) }}
            classNames={{ root: "canvas-popover canvas-composer-settings canvas-workflow-settings" }} content={parameterContent(false)}>
            <Button className="canvas-composer-parameters" size="small" aria-label="创作参数" aria-expanded={parametersOpen}
              title={summary.join(" · ")}>{compactSummary.join(" · ") || "参数"}{parametersOpen ? <ChevronUp size={12} /> : <ChevronDown size={12} />}</Button>
          </Popover>
        ) : null}
        {isImage && (mode.max_references ?? 0) > 0 ? (
          <Tooltip title="引用参考图">
            {pictures.length ? (
              <Dropdown trigger={["click"]} placement="topLeft" classNames={{ root: "canvas-popup" }} menu={{
                items: pictures.map((reference, index) => ({ key: String(index + 1), label: `${canvasPictureToken(index + 1)} · ${canvasReferenceLabel(reference, index + 1)}` })),
                onClick: ({ key }) => setPrompt((current) => `${current} ${canvasPictureToken(Number(key))}`.trim()),
              }}><Button type="text" className="canvas-composer-reference-trigger" size="small" icon={<AtSign size={16} />} aria-label="引用参考图" /></Dropdown>
            ) : <Button type="text" className="canvas-composer-reference-trigger" size="small" icon={<AtSign size={16} />} aria-label="引用参考图"
              onClick={() => onRun(runState(), { submit: false, referenceKind: "image" })} />}
          </Tooltip>
        ) : null}
        {fields.advanced.length ? (
          <Popover trigger="click" placement="topRight" arrow={false} open={advancedOpen}
            onOpenChange={(open) => { setAdvancedOpen(open); if (open) setParametersOpen(false) }}
            classNames={{ root: "canvas-popover canvas-composer-settings canvas-workflow-settings" }} title="更多设置" content={parameterContent(true)}>
            <Button size="small" className="canvas-composer-more" icon={<SlidersHorizontal size={14} />} aria-label="更多设置" />
          </Popover>
        ) : null}
        <div className="canvas-composer-submit">
          {mode?.billing?.enabled && authenticated ? (
            <CanvasCreditEstimate mode={mode} values={values} referenceCount={references.length} authenticated={authenticated} />
          ) : null}
          <Button type="primary" size="small" disabled={Boolean(issue) || modesLoading || !mode}
            title={issue || "按当前参数新建生成节点并开始生成"}
            icon={<Sparkles size={14} />} onClick={() => onRun(runState(), { submit: true })}>生成</Button>
        </div>
      </div>
    </section>
  )
}
