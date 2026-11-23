import { useReactFlow } from "@xyflow/react"
import { Button, Dropdown, Input, message, Popover, Radio, Segmented, Select, Tooltip } from "antd"
import { AtSign, AudioLines, ChevronDown, ChevronUp, FileImage, FolderOpen, Image as ImageIcon, MousePointer2, Plus, RefreshCw, Scan, Settings, SlidersHorizontal, Sparkles, Square, Type, Upload, Video, X } from "lucide-react"
import { Fragment, useState, type KeyboardEvent, type ReactNode } from "react"
import { isSubmitEnter } from "../lib/enter-submit"
import { searchFilterOption } from "../search-match"
import { CanvasCreditEstimate } from "./CanvasCreditEstimate"
import type { CanvasGeneratorContextValue, CanvasNodeActions } from "./node-primitives"
import { GeneratorOptionField } from "./CanvasGeneratorInspector"
import { canvasComposerOptionChoices, canvasComposerOptionLabel, canvasComposerParameterLayout, canvasReferenceSlots } from "./canvas-composer"
import { parseCanvasFrameRatio } from "./canvas-frame"
import {
  canvasPictureToken, canvasReferenceKind, canvasReferenceLabel, canvasReferencePreviewUrl, canvasReferenceUrl, canvasWorkflowChangePatch, generatorOptionValues,
  generatorParameterSummary, isCanvasJobActive, pickCanvasReferenceUpgradeMode, type CanvasOptionValue, type CanvasReferenceKind,
} from "./canvas-generation"
import type { CanvasNode } from "./canvas-model"
import { useCanvasTextDraft } from "./useCanvasTextDraft"

export function CanvasGeneratorComposer({ id, data, generator, actions, authenticated = true }: {
  id: string
  data: CanvasNode["data"]
  generator: CanvasGeneratorContextValue
  actions: CanvasNodeActions
  authenticated?: boolean
}) {
  const { updateNodeData } = useReactFlow<CanvasNode>()
  const [parametersOpen, setParametersOpen] = useState(false)
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [referencePreviewId, setReferencePreviewId] = useState<string | null>(null)
  const [referenceMenuId, setReferenceMenuId] = useState<string | null>(null)
  const mode = generator.modeFor(data.workflowId)
  const isImage = mode?.media_type === "image"
  const live = generator.liveFor(data.jobId)
  const status = live?.status ?? data.jobStatus
  const active = isCanvasJobActive(status)
  const confirming = status === "awaiting_refine"
  const busy = generator.submitting(id)
  const locked = active || busy
  const prompt = generator.promptInfoFor(id)
  const promptDraft = useCanvasTextDraft(prompt.fromTextNodes ? prompt.text : data.prompt || "",
    (value) => updateNodeData(id, { prompt: value }))
  const issue = generator.issueFor(id)
  const references = generator.referencesFor(id)
  const pictures = references.filter((node) => canvasReferenceKind(node) === "image")
  // 即梦式：参考位只呈现当前工作流可用的素材；连入但用不上的素材（0 参考位或槽位不符）不占参考位，
  // 由校验提示与画布连线负责，避免出现「把节点自身当参考」的误解。
  const slots = canvasReferenceSlots(mode, references).filter(({ unmatched }) => !unmatched)
  // 0 参考位的图片工作流仍提供加号：添加时自动切到同系可接参考的工作流（如文生图 → 多参考编辑）。
  const referenceUpgradeMode = isImage && mode && (mode.max_references ?? 0) === 0
    ? pickCanvasReferenceUpgradeMode(generator.modes, mode, "image")
    : null
  const upgradeWorkflowForReference = (method: "upload" | "library" | "canvas") => {
    setReferenceMenuId(null)
    setReferencePreviewId(null)
    if (!mode || (mode.max_references ?? 0) > 0) {
      generator.chooseReferenceSource(id, "image", null, method)
      return
    }
    if (!referenceUpgradeMode) {
      message.warning(`「${mode.name}」不支持参考图，请先更换工作流`)
      return
    }
    // canvasWorkflowChangePatch 传入当前数据：只换工作流与参数默认值，保留节点上已展示的生成结果。
    updateNodeData(id, canvasWorkflowChangePatch(referenceUpgradeMode.id, referenceUpgradeMode, data))
    message.success(`已切换到「${referenceUpgradeMode.name}」，继续添加参考图`)
    generator.chooseReferenceSource(id, "image", null, method)
  }
  const [inlineReferenceIds, setInlineReferenceIds] = useState<string[]>([])
  const [inlinePreviewId, setInlinePreviewId] = useState<string | null>(null)
  const inlineReferences = inlineReferenceIds.flatMap((nodeId) => {
    const slot = slots.find((item) => item.node?.id === nodeId && item.kind === "image")
    const node = slot?.node
    if (!node) return []
    const url = canvasReferencePreviewUrl(node, "image")
    return url ? [{ node, slotLabel: slot.label, index: slot.index, url }] : []
  })
  const insertInlineReference = (node: CanvasNode) => {
    setReferencePreviewId(null)
    setInlineReferenceIds((current) => current.includes(node.id) ? current : [...current, node.id])
  }
  const showsSlotLabels = mode?.reference_mode === "keyframes" || slots.some(({ kind }) => kind !== "image")
  const values = generatorOptionValues(mode, data.optionValues)
  const fields = canvasComposerParameterLayout(mode, values)
  const settingsFields = [...fields.visual.flatMap(({ field, companions }) => [field, ...companions]), ...fields.primary]
  const summary = generatorParameterSummary(mode, values)
  const compactSummary = settingsFields.filter(([, definition]) => definition.type !== "boolean").slice(0, 3)
    .map(([name, definition]) => canvasComposerOptionLabel(definition, values[name])).filter(Boolean)
  const changeOption = (name: string, value: CanvasOptionValue) => updateNodeData(id, { optionValues: { ...values, [name]: value } })

  const referenceSourceItems = (kind: CanvasReferenceKind) => [
    { key: "upload", icon: <Upload size={15} />, label: kind === "image" ? "上传图片" : kind === "video" ? "上传视频" : "上传音频", disabled: kind === "audio" },
    { key: "library", icon: <FolderOpen size={15} />, label: "从资产库添加" },
    { key: "canvas", icon: <MousePointer2 size={15} />, label: "从画布选择" },
  ]

  const chooseReferenceSource = (kind: CanvasReferenceKind, sourceId: string | null, method: "upload" | "library" | "canvas") => {
    setReferenceMenuId(null)
    setReferencePreviewId(null)
    setInlinePreviewId(null)
    generator.chooseReferenceSource(id, kind, sourceId, method)
  }

  const referenceMenu = (kind: CanvasReferenceKind, sourceId: string | null) => ({
    items: referenceSourceItems(kind),
    onClick: ({ key }: { key: string }) => chooseReferenceSource(kind, sourceId, key as "upload" | "library" | "canvas"),
  })

  const containKeys = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") { setParametersOpen(false); setAdvancedOpen(false) }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
      event.preventDefault()
      actions.saveCanvas()
    }
    event.stopPropagation()
  }

  const genericReferenceName = /^(?:生成|画面生成|生成图片|生成视频|图片生成|视频生成|音频生成)(?:\s*\d+)?$/
  const referenceDisplayName = (node: CanvasNode, index: number) => {
    const name = canvasReferenceLabel(node, index)
    if (!genericReferenceName.test(name)) return name
    const detail = [node.data.caption, node.data.prompt]
      .map((value) => String(value ?? "").replace(/\s+/g, " ").trim())
      .find((value) => value && !genericReferenceName.test(value))
    if (!detail) return ""
    return detail.length > 48 ? `${detail.slice(0, 48)}…` : detail
  }

  const referencePreviewCard = (node: CanvasNode, index: number, label: string, imagePreview: string, action?: ReactNode) => {
    const name = referenceDisplayName(node, index)
    return (
      <figure className="canvas-reference-preview-card">
        <img src={imagePreview} alt={name || label} draggable={false} />
        {action ? <div className="canvas-reference-preview-actions">{action}</div> : null}
      </figure>
    )
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
          if (choice) changeOption(name, choice.value)
        }
        return choices.length && definition.type !== "boolean" ? (
          <fieldset key={name} className="canvas-workflow-setting-field">
            <legend>{definition.label}{definition.unit ? `（${definition.unit}）` : ""}</legend>
            {!segmented ? (
              <Radio.Group className={`canvas-setting-choices${visual ? " is-ratio" : ""}`} aria-label={definition.label} name={`canvas-option-${id}-${name}`}
                style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }} value={String(values[name] ?? definition.default)}
                disabled={locked} onChange={(event) => setChoice(event.target.value)}>
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
              <Segmented block className="canvas-setting-segments" aria-label={definition.label} name={`canvas-option-${id}-${name}`}
                value={String(values[name] ?? definition.default)} disabled={locked}
                options={choices.map((choice) => ({ value: String(choice.value), title: choice.label,
                  label: <span className="canvas-setting-choice-label"><span>{choice.short_label || choice.label}</span>{choice.short_label && choice.hint ? <small>{choice.hint}</small> : null}</span>,
                }))} onChange={setChoice} />
            )}
            {definition.description ? <p className="canvas-setting-hint">{definition.description}</p> : null}
          </fieldset>
        ) : <GeneratorOptionField key={name} name={name} definition={definition} value={values[name]} disabled={locked} onChange={changeOption} />
      })}
    </div>
  )

  return (
    <section className={`canvas-creative-panel canvas-generator-composer nodrag nopan nowheel${isImage ? " is-image" : ""}`} aria-label="节点生成区"
      onPointerDown={(event) => event.stopPropagation()} onDoubleClick={(event) => event.stopPropagation()}
      onKeyDown={containKeys}>
      {(slots.length || referenceUpgradeMode) ? (
        <div className="canvas-composer-references" aria-label="参考素材">
          {slots.map(({ index, node, kind, required, label }) => {
            const url = node ? canvasReferenceUrl(node, kind) : null
            // 即梦式占位：上游节点还没产出内容时引用保持可见，但置灰不可点，悬浮提示节点内容为空。
            const empty = Boolean(node) && !url
            const thumbnail = kind === "image" ? node ? canvasReferencePreviewUrl(node, kind) : null : kind === "video" ? node?.data.cover : null
            const sameKind = references.filter((reference) => canvasReferenceKind(reference) === kind)
            const position = node ? sameKind.indexOf(node) : -1
            const picture = kind === "image" && position >= 0 ? canvasPictureToken(position + 1) : null
            const requirement = required ? "（必填）" : "（可选）"
            const sourceLabel = node ? canvasReferenceLabel(node, index + 1) : ""
            const imagePreview = kind === "image" && node && thumbnail ? thumbnail : null
            const slotKey = `reference-slot-${index}`
            const referenceTitle = !node ? `${label}${requirement}`
              : empty ? `${label}${requirement} · 节点内容为空`
              : `${label}${requirement} · ${sourceLabel}`
            const previewButton = (
              <Button type="text" className="canvas-composer-reference-preview" disabled={locked || empty}
                title={!node ? referenceTitle : undefined}
                aria-label={node ? empty ? `${label}（节点内容为空）` : kind === "image" ? `参考图 ${index + 1}` : `${kind === "audio" ? "定位" : "替换"}${label}` : `添加${label}${requirement}`}
                aria-haspopup={node ? undefined : "menu"} aria-expanded={node ? undefined : referenceMenuId === slotKey}
                onClick={node ? () => {
                  if (kind === "image") {
                    insertInlineReference(node)
                    return
                  }
                  generator.chooseReference(id, kind, node.id)
                } : undefined}>
                {!node ? <Plus size={19} /> : thumbnail ? <img src={thumbnail} alt={label} draggable={false} />
                  : kind === "video" ? <Video size={19} /> : kind === "audio" ? <AudioLines size={19} /> : <ImageIcon size={19} />}
                {node ? <span className="canvas-composer-reference-number">{index + 1}</span> : null}
                {showsSlotLabels ? <span className="canvas-composer-reference-label">{label}{required ? " *" : mode?.reference_mode === "keyframes" ? " · 可选" : ""}</span> : null}
              </Button>
            )
            const tile = (
              <div className={`canvas-composer-reference${node ? " is-filled" : ""}${empty ? " is-empty" : ""}`}>
                {imagePreview && node ? (
                  <Popover trigger="hover" placement="top" arrow={false} mouseEnterDelay={0.2} mouseLeaveDelay={0.08}
                    open={!locked && (referencePreviewId === node.id || referenceMenuId === node.id)}
                    onOpenChange={(open) => {
                      // 指针移入替换菜单时先保持大图预览，避免菜单的触发按钮被卸载。
                      if (!open && referenceMenuId === node.id) return
                      setReferencePreviewId(open && !locked ? node.id : null)
                    }}
                    classNames={{ root: "canvas-popover canvas-reference-preview" }}
                    content={referencePreviewCard(node, index, label, imagePreview,
                      <Dropdown trigger={["hover", "click"]} placement="topRight" arrow={false}
                        open={referenceMenuId === node.id}
                        onOpenChange={(open) => {
                          setReferenceMenuId(open ? node.id : null)
                          if (!open) setReferencePreviewId((current) => current === node.id ? null : current)
                        }}
                        classNames={{ root: "canvas-popup canvas-reference-replace-menu" }}
                        menu={referenceMenu(kind, node.id)}>
                        <Button type="text" shape="circle" className="canvas-reference-preview-replace" icon={<RefreshCw size={13} />}
                          aria-label={`替换${label}`} aria-haspopup="menu" aria-expanded={referenceMenuId === node.id} />
                      </Dropdown>
                    )}>
                    {previewButton}
                  </Popover>
                ) : node ? (
                  <Tooltip title={referenceTitle}>
                    {previewButton}
                  </Tooltip>
                ) : (
                  <Dropdown trigger={["click"]} placement="top" arrow={false}
                    open={referenceMenuId === slotKey}
                    onOpenChange={(open) => {
                      setReferenceMenuId(open ? slotKey : null)
                      if (!open) setReferencePreviewId(null)
                    }}
                    classNames={{ root: "canvas-popup canvas-reference-replace-menu" }}
                    menu={referenceMenu(kind, null)}>
                    {previewButton}
                  </Dropdown>
                )}
                {node ? (
                  <Button type="text" size="small" className="canvas-composer-reference-remove" icon={<X size={11} />}
                    disabled={locked} aria-label={`移除${label}`}
                    onClick={(event) => { event.stopPropagation(); setReferencePreviewId(null); generator.removeReference(id, node.id) }} />
                ) : null}
              </div>
            )
            return node ? (
              <Dropdown key={node.id} trigger={["contextMenu"]} disabled={locked} classNames={{ root: "canvas-popup" }} menu={{
                items: [
                  ...(picture ? [{ key: "token", label: `插入 ${picture}`, disabled: prompt.fromTextNodes }] : []),
                  { key: "left", label: "向前移动", disabled: position <= 0 },
                  { key: "right", label: "向后移动", disabled: position >= sameKind.length - 1 },
                  { key: "remove", label: "移除参考", danger: true },
                ],
                onClick: ({ key }) => {
                  if (key === "token" && picture) updateNodeData(id, { prompt: `${promptDraft.value} ${picture}`.trim() })
                  if (key === "left" || key === "right") generator.moveReference(id, node.id, key === "left" ? -1 : 1)
                  if (key === "remove") generator.removeReference(id, node.id)
                },
              }}>{tile}</Dropdown>
            ) : <Fragment key={`slot-${index}`}>{tile}</Fragment>
          })}
          {referenceUpgradeMode ? (
            <div className="canvas-composer-reference" key="zero-ref-add">
              <Dropdown trigger={["click"]} placement="top" arrow={false}
                open={referenceMenuId === "zero-ref-add"}
                onOpenChange={(open) => {
                  setReferenceMenuId(open ? "zero-ref-add" : null)
                  if (!open) setReferencePreviewId(null)
                }}
                classNames={{ root: "canvas-popup canvas-reference-replace-menu" }}
                menu={{
                  items: referenceSourceItems("image"),
                  onClick: ({ key }) => upgradeWorkflowForReference(key as "upload" | "library" | "canvas"),
                }}>
                <Button type="text" className="canvas-composer-reference-preview" disabled={locked}
                  title={`当前工作流不使用参考图，添加后将切换到「${referenceUpgradeMode.name}」`}
                  aria-label="添加参考图" aria-haspopup="menu" aria-expanded={referenceMenuId === "zero-ref-add"}>
                  <Plus size={19} />
                </Button>
              </Dropdown>
            </div>
          ) : null}
        </div>
      ) : null}
      {prompt.fromTextNodes ? (
        <div className="canvas-composer-text-source"><Type size={12} />来自 {prompt.connectedTextNodes} 个文字节点
          <Button type="text" size="small" disabled={locked} onClick={() => generator.disconnectInput(id, "text")}>断开</Button>
        </div>
      ) : null}
      {inlineReferences.length ? (
        <div className="canvas-composer-inline-references" aria-label="输入框中的参考图">
          {inlineReferences.map((item) => (
            <Popover key={item.node.id} trigger="hover" placement="top" arrow={false}
              mouseEnterDelay={0.2} mouseLeaveDelay={0.08}
              open={!locked && inlinePreviewId === item.node.id}
              onOpenChange={(open) => setInlinePreviewId(open && !locked ? item.node.id : null)}
              classNames={{ root: "canvas-popover canvas-reference-preview" }}
              content={referencePreviewCard(item.node, item.index, item.slotLabel, item.url)}>
              <button type="button" className="canvas-composer-inline-reference" title={item.slotLabel}
                aria-label={`预览${item.slotLabel}`}>
                <FileImage size={13} />
                <span>{item.slotLabel}</span>
              </button>
            </Popover>
          ))}
        </div>
      ) : null}
      <Input.TextArea id={`canvas-generator-prompt-${id}`} aria-label={prompt.fromTextNodes ? "来自文字节点的提示词" : "生成提示词"}
        className="canvas-composer-prompt" value={promptDraft.value}
        variant="borderless" readOnly={prompt.fromTextNodes} disabled={locked} autoSize={{ minRows: 2, maxRows: 5 }} maxLength={4000}
        placeholder={inlineReferences.length ? "" : mode?.media_type === "video" ? "描述画面、镜头与动作…" : "描述你想生成的画面…"}
        onFocus={promptDraft.onFocus} onBlur={promptDraft.onBlur}
        onCompositionStart={promptDraft.onCompositionStart}
        onCompositionEnd={(event) => promptDraft.onCompositionEnd(event.currentTarget.value)}
        onChange={(event) => promptDraft.onChange(event.target.value)}
        onKeyDown={(event) => {
          // 回车直接生成；Shift / Alt + Enter 换行，输入法组合期间不触发。
          if (!isSubmitEnter(event)) return
          event.preventDefault()
          if (!locked && !issue && !generator.modesLoading) generator.submit(id)
        }} />
      {!active && issue ? <div className="canvas-composer-validation" role="status">{issue}</div> : null}
      <div className="canvas-composer-controls">
        <Select aria-label="节点生成工作流" className="canvas-composer-workflow" size="small" placement="topLeft"
          variant="borderless"
          classNames={{ popup: { root: "canvas-select-popup" } }} popupMatchSelectWidth={280}
          value={mode?.id} placeholder="选择工作流" loading={generator.modesLoading} disabled={locked}
          showSearch filterOption={searchFilterOption} options={generator.modes.map((item) => ({ value: item.id, label: item.name }))}
          onChange={(value) => { setParametersOpen(false); setAdvancedOpen(false); updateNodeData(id, canvasWorkflowChangePatch(value, generator.modeFor(value), data)) }} />
        {fields.primary.length || fields.visual.length ? (
          <Popover trigger="click" placement="topLeft" arrow={false} open={parametersOpen}
            onOpenChange={(open) => { setParametersOpen(open); if (open) setAdvancedOpen(false) }}
            classNames={{ root: "canvas-popover canvas-composer-settings canvas-workflow-settings" }} content={parameterContent(false)}>
            <Button className="canvas-composer-parameters" size="small" disabled={locked} aria-label="创作参数" aria-expanded={parametersOpen}
              title={summary.join(" · ")}>{compactSummary.join(" · ") || "参数"}{parametersOpen ? <ChevronUp size={12} /> : <ChevronDown size={12} />}</Button>
          </Popover>
        ) : null}
        {isImage && (mode.max_references ?? 0) > 0 ? (
          <Tooltip title="引用参考图">
            {pictures.length ? (
              <Dropdown trigger={["click"]} placement="topLeft" disabled={locked} classNames={{ root: "canvas-popup" }} menu={{
                items: [
                  ...pictures.map((node, index) => ({ key: String(index + 1), label: `${canvasPictureToken(index + 1)} · ${canvasReferenceLabel(node, index + 1)}`, disabled: prompt.fromTextNodes })),
                  { type: "divider" },
                  { key: "add", label: "添加参考图", disabled: references.length >= (mode.max_references ?? 0) },
                ],
                onClick: ({ key }) => {
                  if (key === "add") generator.chooseReference(id, "image")
                  else updateNodeData(id, { prompt: `${promptDraft.value} ${canvasPictureToken(Number(key))}`.trim() })
                },
              }}><Button type="text" className="canvas-composer-reference-trigger" size="small" icon={<AtSign size={16} />} aria-label="引用参考图" disabled={locked} /></Dropdown>
            ) : <Button type="text" className="canvas-composer-reference-trigger" size="small" icon={<AtSign size={16} />} aria-label="引用参考图" disabled={locked || references.length >= (mode.max_references ?? 0)} onClick={() => generator.chooseReference(id, "image")} />}
          </Tooltip>
        ) : null}
        {fields.advanced.length ? (
          <Popover trigger="click" placement="topRight" arrow={false} open={advancedOpen}
            onOpenChange={(open) => { setAdvancedOpen(open); if (open) setParametersOpen(false) }}
            classNames={{ root: "canvas-popover canvas-composer-settings canvas-workflow-settings" }} title="更多设置" content={parameterContent(true)}>
            <Button size="small" className="canvas-composer-more" disabled={locked} icon={<SlidersHorizontal size={14} />} aria-label="更多设置" />
          </Popover>
        ) : <Tooltip title="节点属性"><Button size="small" className="canvas-composer-more" icon={<Settings size={14} />} onClick={() => actions.openProperties(id)} aria-label="节点属性" /></Tooltip>}
        <div className="canvas-composer-submit">
          {/* 积分预估只伴随「生成/重试」按钮展示；二采与停止生成阶段另有确认语义。 */}
          {!confirming && !active && mode?.billing?.enabled && authenticated ? (
            <CanvasCreditEstimate mode={mode} values={values} referenceCount={references.length} authenticated={authenticated} />
          ) : null}
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
      {!isImage && pictures.length && !prompt.fromTextNodes ? (
        <Dropdown trigger={["click"]} disabled={locked} classNames={{ root: "canvas-popup" }} menu={{
          items: pictures.map((node, index) => ({ key: String(index + 1), label: `${canvasPictureToken(index + 1)} · ${canvasReferenceLabel(node, index + 1)}` })),
          onClick: ({ key }) => updateNodeData(id, { prompt: `${promptDraft.value} ${canvasPictureToken(Number(key))}`.trim() }),
        }}><Button className="canvas-composer-token" type="text" size="small" icon={<ImageIcon size={11} />} disabled={locked}>插入参考图标记</Button></Dropdown>
      ) : null}
    </section>
  )
}
