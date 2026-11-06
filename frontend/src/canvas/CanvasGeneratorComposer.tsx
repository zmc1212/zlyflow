import { useReactFlow } from "@xyflow/react"
import { Button, Dropdown, Input, Popover, Select, Tooltip } from "antd"
import { ChevronDown, ChevronLeft, ChevronRight, Image as ImageIcon, Plus, Settings, SlidersHorizontal, Sparkles, Square, Type, X } from "lucide-react"
import { useEffect, useRef, type KeyboardEvent } from "react"
import type { CanvasGeneratorContextValue, CanvasNodeActions } from "./CanvasNodes"
import { GeneratorOptionField } from "./CanvasGeneratorInspector"
import { canvasReferenceSlots } from "./canvas-composer"
import {
  canvasImageReferenceUrl, canvasPictureToken, canvasWorkflowChangePatch, generatorOptionValues,
  generatorParameterFields, generatorParameterSummary, isCanvasJobActive, type CanvasOptionValue,
} from "./canvas-generation"
import type { CanvasNode } from "./canvas-model"

export function CanvasGeneratorComposer({ id, data, generator, actions }: {
  id: string
  data: CanvasNode["data"]
  generator: CanvasGeneratorContextValue
  actions: CanvasNodeActions
}) {
  const { updateNodeData, getViewport, setViewport } = useReactFlow<CanvasNode>()
  const root = useRef<HTMLDivElement>(null)
  const mode = generator.modeFor(data.workflowId)
  const live = generator.liveFor(data.jobId)
  const status = live?.status ?? data.jobStatus
  const active = isCanvasJobActive(status)
  const confirming = status === "awaiting_refine"
  const busy = generator.submitting(id)
  const locked = active || busy
  const prompt = generator.promptInfoFor(id)
  const issue = generator.issueFor(id)
  const references = generator.referencesFor(id)
  const slots = canvasReferenceSlots(mode, references)
  const values = generatorOptionValues(mode, data.optionValues)
  const fields = generatorParameterFields(mode, values)
  const summary = generatorParameterSummary(mode, values)
  const changeOption = (name: string, value: CanvasOptionValue) => updateNodeData(id, { optionValues: { ...values, [name]: value } })

  // Reveal the selected node's composer without moving any saved graph nodes.
  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      const element = root.current
      const stage = element?.closest(".react-flow")
      const card = stage ? Array.from(stage.querySelectorAll(".react-flow__node")).find((node) => node.getAttribute("data-id") === id) : null
      if (!element || !stage || !card) return
      const bounds = element.getBoundingClientRect()
      const area = stage.getBoundingClientRect()
      const top = card.getBoundingClientRect().top
      const overflow = bounds.bottom - area.bottom + 66
      if (overflow <= 0) return
      const shift = Math.min(overflow, Math.max(0, top - area.top - 78))
      if (shift > 0) {
        const viewport = getViewport()
        void setViewport({ ...viewport, y: viewport.y - shift }, { duration: 180 })
      }
    })
    return () => cancelAnimationFrame(frame)
  }, [getViewport, id, setViewport])

  const containKeys = (event: KeyboardEvent<HTMLDivElement>) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
      event.preventDefault()
      actions.saveCanvas()
    }
    event.stopPropagation()
  }

  const parameterContent = (advanced: boolean) => (
    <div className="canvas-composer-option-fields nodrag nopan nowheel" onKeyDown={containKeys}>
      {(advanced ? fields.advanced : fields.primary).map(([name, definition]) => (
        <GeneratorOptionField key={name} name={name} definition={definition} value={values[name]} disabled={locked} onChange={changeOption} />
      ))}
    </div>
  )

  return (
    <div ref={root} className="canvas-generator-composer nodrag nopan nowheel" aria-label="节点生成区"
      onPointerDown={(event) => event.stopPropagation()} onDoubleClick={(event) => event.stopPropagation()}
      onKeyDown={containKeys}>
      {slots.length ? (
        <div className="canvas-composer-references" aria-label="有序参考图">
          {slots.map(({ index, node, required, label }) => {
            const url = node ? node.data.url || node.data.resultUrl || canvasImageReferenceUrl(node.data) : null
            return (
              <div className={`canvas-composer-reference${node ? " is-filled" : ""}`} key={node?.id ?? `slot-${index}`}>
                <Tooltip title={`${label}${required ? "（必填）" : "（可选）"}${node ? ` · ${node.data.label || "参考图"}` : ""}`}>
                  <Button type="text" className="canvas-composer-reference-preview" disabled={locked}
                    aria-label={node ? `替换${label}` : `添加${label}${required ? "（必填）" : "（可选）"}`}
                    onClick={() => generator.chooseReference(id, node?.id)}>
                    {url ? <img src={url} alt={label} draggable={false} /> : <Plus size={19} />}
                    <span className="canvas-composer-reference-number">{index + 1}</span>
                    {mode?.reference_mode === "keyframes" ? <span className="canvas-composer-reference-label">{label}{required ? " *" : " · 可选"}</span> : null}
                  </Button>
                </Tooltip>
                {node ? (
                  <Dropdown trigger={["contextMenu"]} disabled={locked} classNames={{ root: "canvas-popup" }} menu={{
                    items: [
                      { key: "token", label: `插入 ${canvasPictureToken(index + 1)}`, disabled: prompt.fromTextNodes },
                      { key: "left", label: "向前移动", disabled: index === 0 },
                      { key: "right", label: "向后移动", disabled: index === references.length - 1 },
                      { key: "remove", label: "移除参考", danger: true },
                    ],
                    onClick: ({ key }) => {
                      if (key === "token") updateNodeData(id, { prompt: `${data.prompt || ""} ${canvasPictureToken(index + 1)}`.trim() })
                      if (key === "left" || key === "right") generator.moveReference(id, node.id, key === "left" ? -1 : 1)
                      if (key === "remove") generator.removeReference(id, node.id)
                    },
                  }}>
                    <div className="canvas-composer-reference-tools">
                      <Button type="text" size="small" icon={<ChevronLeft size={10} />} disabled={locked || index === 0} aria-label={`将参考图 ${index + 1} 向前移动`} onClick={() => generator.moveReference(id, node.id, -1)} />
                      <Button type="text" size="small" icon={<ChevronRight size={10} />} disabled={locked || index === references.length - 1} aria-label={`将参考图 ${index + 1} 向后移动`} onClick={() => generator.moveReference(id, node.id, 1)} />
                      <Button type="text" size="small" icon={<X size={10} />} disabled={locked} aria-label={`移除参考图 ${index + 1}`} onClick={() => generator.removeReference(id, node.id)} />
                    </div>
                  </Dropdown>
                ) : null}
              </div>
            )
          })}
        </div>
      ) : null}
      {prompt.fromTextNodes ? (
        <div className="canvas-composer-text-source"><Type size={12} />来自 {prompt.connectedTextNodes} 个文字节点
          <Button type="text" size="small" disabled={locked} onClick={() => generator.disconnectInput(id, "text")}>断开</Button>
        </div>
      ) : null}
      <Input.TextArea id={`canvas-generator-prompt-${id}`} aria-label={prompt.fromTextNodes ? "来自文字节点的提示词" : "生成提示词"}
        className="canvas-composer-prompt" value={prompt.fromTextNodes ? prompt.text : data.prompt || ""}
        readOnly={prompt.fromTextNodes} disabled={locked} autoSize={{ minRows: 2, maxRows: 5 }} maxLength={4000}
        placeholder={mode?.media_type === "video" ? "描述画面、镜头与动作…" : "描述你想生成的画面…"}
        onChange={(event) => updateNodeData(id, { prompt: event.target.value })} />
      {!active && issue ? <div className="canvas-composer-validation" role="status">{issue}</div> : null}
      <div className="canvas-composer-controls">
        <Select aria-label="节点生成工作流" className="canvas-composer-workflow" size="small"
          classNames={{ popup: { root: "canvas-select-popup" } }} popupMatchSelectWidth={280}
          value={mode?.id} placeholder="选择工作流" loading={generator.modesLoading} disabled={locked}
          showSearch optionFilterProp="label" options={generator.modes.map((item) => ({ value: item.id, label: item.name }))}
          onChange={(value) => updateNodeData(id, canvasWorkflowChangePatch(value, generator.modeFor(value)))} />
        {fields.primary.length ? (
          <Popover trigger="click" placement="bottom" classNames={{ root: "canvas-popover canvas-composer-settings" }} title="创作参数" content={parameterContent(false)}>
            <Button className="canvas-composer-parameters" size="small" disabled={locked} aria-label="创作参数" title={summary.join(" · ")}>{summary.map((item) => item.replace(/^\S+ /, "")).join(" · ") || "参数"}<ChevronDown size={11} /></Button>
          </Popover>
        ) : null}
        {fields.advanced.length ? (
          <Popover trigger="click" placement="bottomRight" classNames={{ root: "canvas-popover canvas-composer-settings" }} title="更多设置" content={parameterContent(true)}>
            <Button size="small" className="canvas-composer-more" disabled={locked} icon={<SlidersHorizontal size={14} />} aria-label="更多设置" />
          </Popover>
        ) : <Tooltip title="节点属性"><Button size="small" className="canvas-composer-more" icon={<Settings size={14} />} onClick={() => actions.openProperties(id)} aria-label="节点属性" /></Tooltip>}
        <div className="canvas-composer-submit">
          {confirming ? <>
            <Button type="primary" size="small" loading={busy} onClick={() => generator.refine(id, "confirm")}>确认二采</Button>
            <Button size="small" disabled={busy} onClick={() => generator.refine(id, "skip")}>保留一采</Button>
          </> : active ? (
            <Button size="small" loading={busy} icon={<Square size={12} />} onClick={() => generator.cancel(id)}>停止生成</Button>
          ) : (
            <Button type="primary" size="small" loading={busy} disabled={Boolean(issue) || generator.modesLoading} title={issue || undefined}
              icon={<Sparkles size={14} />} onClick={() => generator.submit(id)}>{status === "failed" ? "重试" : data.resultUrl ? "再次生成" : "生成"}</Button>
          )}
        </div>
      </div>
      {references.length && !prompt.fromTextNodes ? (
        <Dropdown trigger={["click"]} disabled={locked} classNames={{ root: "canvas-popup" }} menu={{
          items: references.map((node, index: number) => ({ key: String(index + 1), label: `${canvasPictureToken(index + 1)} · ${node.data.label || "参考图"}` })),
          onClick: ({ key }) => updateNodeData(id, { prompt: `${data.prompt || ""} ${canvasPictureToken(Number(key))}`.trim() }),
        }}><Button className="canvas-composer-token" type="text" size="small" icon={<ImageIcon size={11} />} disabled={locked}>插入参考图标记</Button></Dropdown>
      ) : null}
    </div>
  )
}
