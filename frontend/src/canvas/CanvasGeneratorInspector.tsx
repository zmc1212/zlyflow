import { useReactFlow } from "@xyflow/react"
import { Alert, Button, Collapse, Dropdown, Input, InputNumber, Select, Switch, Tag, Typography } from "antd"
import {
  ChevronDown, ChevronLeft, ChevronRight, Image as ImageIcon, LoaderCircle, Play, Plus,
  Sparkles, Square, Type, Video,
} from "lucide-react"
import { useId, useMemo } from "react"
import { searchFilterOption } from "../search-match"
import type { CanvasMediaPreview } from "./CanvasNodes"
import {
  canvasImageReferenceUrl,
  canvasJobStatusLabel,
  canvasJobStatusTone,
  canvasPictureToken,
  canvasReferenceLabel,
  canvasResultHistory,
  canvasResultVersionIndex,
  canvasRunSnapshotForJob,
  canvasWorkflowChangePatch,
  generatorOptionValues,
  generatorParameterFields,
  generatorPromptInfo,
  generatorPromptIssue,
  generatorReferenceIssue,
  displayedGeneratorResult,
  isCanvasJobActive,
  resolveGeneratorPrompt,
  selectCanvasResultVersion,
  validateGeneratorInput,
  type CanvasGeneratorLive,
  type CanvasOptionDefinition,
  type CanvasOptionValue,
  type CanvasWorkflowMode,
} from "./canvas-generation"
import {
  formatCanvasTime,
  type CanvasBranchDirection,
  type CanvasMediaKind,
  type CanvasNode,
} from "./canvas-model"
import { CanvasRunTrace } from "./CanvasRunTrace"

export function CanvasGeneratorInspector({
  node, modes, modesLoading, modesError, onReloadModes, references, promptNodes, live, submitting,
  onPreview, onSubmit, onCancel, onRefine, onInsertResult, onOpenJob,
}: {
  node: CanvasNode
  modes: CanvasWorkflowMode[]
  modesLoading: boolean
  modesError: string | null
  onReloadModes: () => void
  references: CanvasNode[]
  promptNodes: CanvasNode[]
  live: CanvasGeneratorLive | null
  submitting: boolean
  onPreview: (preview: CanvasMediaPreview) => void
  onSubmit: (nodeId: string) => void
  onCancel: (nodeId: string) => void
  onRefine: (nodeId: string, action: "confirm" | "skip") => void
  onInsertResult: (nodeId: string, direction: CanvasBranchDirection) => void
  onOpenJob: (jobId: string, kind?: CanvasMediaKind) => void
}) {
  const { updateNodeData } = useReactFlow()
  const workflow = modes.find((item) => item.id === node.data.workflowId) ?? null
  const values = generatorOptionValues(workflow, node.data.optionValues)
  const fields = generatorParameterFields(workflow, values)
  const promptSource = resolveGeneratorPrompt(promptNodes, node.data.prompt ?? "")
  const promptInfo = generatorPromptInfo(promptSource)
  const promptIssue = workflow ? generatorPromptIssue(promptSource.text, promptInfo) : null
  const referenceIssue = workflow ? generatorReferenceIssue(workflow, references) : null
  const issue = validateGeneratorInput(workflow, promptSource.text, references, promptInfo)
  const jobId = node.data.jobId ?? null
  const status = live?.status ?? node.data.jobStatus ?? null
  const active = isCanvasJobActive(status)
  const result = displayedGeneratorResult(node.data, live)
  const history = canvasResultHistory(node.data)
  const versionIndex = canvasResultVersionIndex(node.data)
  const error = live?.error || node.data.jobError
  const tone = canvasJobStatusTone(status)
  const locked = active || submitting
  const referenceRequirement = workflow
    ? (workflow.min_references ?? 0) === (workflow.max_references ?? 0)
      ? `需要 ${workflow.max_references ?? 0} 张参考图`
      : `支持 ${workflow.min_references ?? 0}-${workflow.max_references ?? 0} 张参考图`
    : "选择工作流后显示参考图要求"

  const workflowGroups = useMemo(() => {
    const groups = new Map<string, { label: string; options: { value: string; label: string }[] }>()
    for (const item of modes) {
      const label = item.catalog_group_label || "工作流"
      const group = groups.get(label) ?? { label, options: [] }
      group.options.push({ value: item.id, label: item.name })
      groups.set(label, group)
    }
    return [...groups.values()]
  }, [modes])

  const changeWorkflow = (workflowId: string) => {
    const nextMode = modes.find((item) => item.id === workflowId) ?? null
    updateNodeData(node.id, canvasWorkflowChangePatch(workflowId, nextMode))
  }

  const changeOption = (name: string, value: CanvasOptionValue) => {
    updateNodeData(node.id, { optionValues: { ...values, [name]: value } })
  }

  const insertPictureToken = (index: number) => {
    const token = canvasPictureToken(index)
    const current = String(node.data.prompt ?? "").trimEnd()
    updateNodeData(node.id, { prompt: current ? `${current} ${token}` : token })
  }

  return (
    <div className="canvas-inspector canvas-generator-inspector">
      {modesError ? (
        <Alert
          type="error"
          showIcon
          message="工作流列表加载失败"
          description={modesError}
          action={<Button size="small" onClick={onReloadModes}>重试</Button>}
        />
      ) : null}

      <section className="canvas-inspector-section">
        <h4 className="canvas-inspector-section-title">生成设置</h4>
        <div className="canvas-inspector-field">
          <span className="canvas-inspector-field-label">工作流</span>
          <Select
            classNames={{ popup: { root: "canvas-select-popup" } }}
            id="canvas-generator-workflow"
            aria-label="生成工作流"
            className="w-full"
            showSearch
            filterOption={searchFilterOption}
            value={workflow?.id}
            loading={modesLoading}
            disabled={locked || modesLoading}
            placeholder={modesLoading ? "正在加载工作流…" : "选择生成工作流"}
            options={workflowGroups}
            onChange={changeWorkflow}
            notFoundContent="没有可用的图像或视频工作流"
          />
          {workflow?.description ? (
            <p className="canvas-inspector-hint">{workflow.description}</p>
          ) : null}
        </div>
        <div className="canvas-inspector-field">
          <div className="canvas-inspector-field-label-row">
            <span className="canvas-inspector-field-label">创作提示词</span>
            {promptSource.fromTextNodes ? (
              <Tag className="canvas-prompt-source-tag" icon={<Type size={11} />}>
                来自 {promptSource.nodes.length} 个文字节点
              </Tag>
            ) : null}
          </div>
          {promptSource.fromTextNodes ? (
            <>
              <div className="canvas-generator-prompt-effective" aria-label="来自文字节点的提示词">
                {promptSource.text || "已连接的文字节点还没有内容"}
              </div>
              <p className="canvas-inspector-hint">
                多个文字节点按连线顺序用空行合并，修改文字节点会即时更新；断开连线后恢复手动提示词。
              </p>
              <div className="canvas-generator-prompt-sources">
                {promptSource.nodes.map((source, index) => {
                  const text = String(source.data.text ?? "").trim()
                  return (
                    <div className="canvas-generator-prompt-source-row" key={source.id}>
                      <span className="canvas-generator-ref-index">{index + 1}</span>
                      <span className={text ? undefined : "is-empty"}>{text || "文字节点内容为空"}</span>
                    </div>
                  )
                })}
              </div>
            </>
          ) : (
            <>
              <Input.TextArea
                id="canvas-generator-prompt"
                name="canvas-generator-prompt"
                aria-label="创作提示词"
                value={node.data.prompt ?? ""}
                autoSize={{ minRows: 4, maxRows: 10 }}
                maxLength={4000}
                showCount
                disabled={locked}
                placeholder="描述画面、镜头、动作与氛围…"
                onChange={(event) => updateNodeData(node.id, { prompt: event.target.value })}
              />
              {references.length ? (
                <Dropdown
                  classNames={{ root: "canvas-popup" }}
                  trigger={["click"]}
                  disabled={locked}
                  menu={{
                    items: references.map((reference, index) => ({
                      key: String(index + 1),
                      label: `${canvasPictureToken(index + 1)} · ${canvasReferenceLabel(reference, index + 1)}`,
                    })),
                    onClick: ({ key }) => insertPictureToken(Number(key)),
                  }}
                >
                  <Button size="small" icon={<Plus size={13} />} disabled={locked}>
                    插入参考图标记
                  </Button>
                </Dropdown>
              ) : null}
              <p className="canvas-inspector-hint">
                提示词中可用 {canvasPictureToken(1)}、{canvasPictureToken(2)} 指代对应序号的参考图。
              </p>
            </>
          )}
          {promptIssue ? <p className="canvas-inspector-hint is-error">{promptIssue}</p> : null}
        </div>

        {fields.primary.length ? (
          <div className="canvas-generator-options">
            {fields.primary.map(([name, definition]) => (
              <GeneratorOptionField
                key={name}
                name={name}
                definition={definition}
                value={values[name]}
                disabled={locked}
                onChange={changeOption}
              />
            ))}
          </div>
        ) : null}

        {fields.advanced.length ? (
          <Collapse
            ghost
            size="small"
            className="canvas-generator-advanced"
            items={[{
              key: "advanced",
              label: `更多设置（${fields.advanced.length}）`,
              children: (
                <div className="canvas-generator-options">
                  {fields.advanced.map(([name, definition]) => (
                    <GeneratorOptionField
                      key={name}
                      name={name}
                      definition={definition}
                      value={values[name]}
                      disabled={locked}
                      onChange={changeOption}
                    />
                  ))}
                </div>
              ),
            }]}
          />
        ) : null}

      </section>

      <section className="canvas-inspector-section">
        <h4 className="canvas-inspector-section-title">参考图</h4>
        <p className="canvas-inspector-hint">{referenceRequirement}，当前已连接 {references.length} 张。</p>
        {references.length ? (
          <div className="canvas-generator-ref-list">
            {references.map((reference, index) => {
              const url = canvasImageReferenceUrl(reference.data)
              const label = canvasReferenceLabel(reference, index + 1)
              return (
                <button
                  type="button"
                  key={reference.id}
                  className="canvas-generator-ref"
                  title={url ? "点击预览参考图" : "参考图没有可用地址"}
                  onClick={() => {
                    if (url) onPreview({ url, label, kind: "image" })
                  }}
                >
                  <span className="canvas-generator-ref-index">{index + 1}</span>
                  <span className="canvas-generator-ref-thumb">
                    {url ? <img src={url} alt="" draggable={false} /> : <ImageIcon size={16} />}
                  </span>
                  <span className="canvas-generator-ref-text">
                    <strong>{label}</strong>
                    <small>
                      {url ? "连线顺序即提交顺序" : "缺少可用图片地址"}
                      {" · "}
                      <code className="canvas-picture-token">{canvasPictureToken(index + 1)}</code>
                    </small>
                  </span>
                </button>
              )
            })}
          </div>
        ) : (
          <p className="canvas-inspector-hint">
            将图片节点连到本节点左侧输入点作为参考图，将文字节点连入则作为提示词。多条连线按创建顺序编号，提交时保持该顺序。
          </p>
        )}
        {references.length ? (
          <p className="canvas-inspector-hint">
            提示词中的 {canvasPictureToken(1)}、{canvasPictureToken(2)} 分别对应第 1、2 张参考图。
          </p>
        ) : null}
        {referenceIssue ? <p className="canvas-inspector-hint is-error">{referenceIssue}</p> : null}
      </section>

      <section className="canvas-inspector-section">
        <h4 className="canvas-inspector-section-title">任务</h4>
        <div className="canvas-generator-status-row">
          <span className={`canvas-generator-status is-${tone}`}>
            {active ? <LoaderCircle size={11} className="animate-spin" /> : null}
            {canvasJobStatusLabel(status)}
          </span>
          {jobId ? (
            <Typography.Text code copyable={{ text: jobId }} ellipsis>{jobId}</Typography.Text>
          ) : (
            <span className="canvas-inspector-empty">尚未提交</span>
          )}
          {active && typeof live?.progress === "number" ? (
            <span className="canvas-generator-progress-value">{Math.round(live.progress)}%</span>
          ) : null}
        </div>
        {active && typeof live?.progress === "number" ? (
          <div
            className="canvas-generator-progress"
            role="progressbar"
            aria-label="生成进度"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(live.progress)}
          >
            <span style={{ width: `${Math.max(3, Math.min(100, live.progress))}%` }} />
          </div>
        ) : null}
        {error ? <Alert type="error" showIcon title="生成失败" description={error} /> : null}
        {status === "awaiting_refine" ? (
          <Alert type="info" showIcon title="一采预览待确认" description="预览后可确认二采精修，或直接保留一采作为成片。" />
        ) : null}
        <div className="canvas-inspector-actions">
          {status === "awaiting_refine" ? <>
            <Button type="primary" loading={submitting} onClick={() => onRefine(node.id, "confirm")}>确认二采</Button>
            <Button disabled={submitting} onClick={() => onRefine(node.id, "skip")}>保留一采</Button>
          </> : (
          <Button
            type="primary"
            icon={<Sparkles size={15} />}
            loading={submitting}
            disabled={locked || Boolean(issue)}
            title={issue ?? undefined}
            onClick={() => onSubmit(node.id)}
          >
            {status === "succeeded" || status === "partial" ? "重新生成" : "提交生成"}
          </Button>
          )}
          {active ? (
            <Button danger disabled={submitting} icon={<Square size={14} />} onClick={() => onCancel(node.id)}>
              停止生成
            </Button>
          ) : null}
        </div>
        {workflow ? <p className="canvas-inspector-hint">{workflow.name} · {referenceRequirement}</p> : null}
      </section>

      <CanvasRunTrace
        title="本次运行"
        jobId={jobId}
        snapshot={canvasRunSnapshotForJob(node.data, jobId)}
        mediaKind={workflow?.media_type ?? node.data.resultKind ?? "image"}
        statusHint={status}
        onOpenJob={onOpenJob}
      />

      {result ? (
        <section className="canvas-inspector-section">
          <h4 className="canvas-inspector-section-title">生成结果</h4>
          <div className="canvas-generator-result-card">
            <button
              type="button"
              className="canvas-generator-result-media"
              title="点击预览结果"
              onClick={() => onPreview({
                url: result.url,
                label: result.label || node.data.label,
                kind: result.kind,
              })}
            >
              {result.kind === "video" ? (
                <video src={result.url} muted loop playsInline preload="metadata" draggable={false} />
              ) : (
                <img src={result.url} alt={result.label || "生成结果"} draggable={false} />
              )}
              <span className="canvas-generator-result-badge">
                {result.kind === "video" ? <Video size={12} /> : <ImageIcon size={12} />}
                {result.kind === "video" ? "视频" : "图片"}
              </span>
            </button>

            {history.length > 1 ? (
              <div className="canvas-result-version-strip">
                {history.map((entry, index) => (
                  <button
                    type="button"
                    key={`${entry.url}-${index}`}
                    className={`canvas-result-version-card${index === versionIndex ? " is-active" : ""}`}
                    title={entry.createdAt ? formatCanvasTime(new Date(entry.createdAt).toISOString()) : `版本 ${index + 1}`}
                    onClick={() => {
                      const patch = selectCanvasResultVersion(node.data, index)
                      if (patch) updateNodeData(node.id, patch)
                    }}
                  >
                    <span className="canvas-result-version-thumb">
                      {entry.kind === "video" ? (
                        <video src={entry.url} muted playsInline preload="metadata" />
                      ) : (
                        <img src={entry.url} alt="" loading="lazy" />
                      )}
                    </span>
                    <span>v{index + 1}</span>
                  </button>
                ))}
              </div>
            ) : null}

            {history.length > 1 ? (
              <div className="canvas-result-version-nav">
                <Button
                  size="small"
                  type="text"
                  icon={<ChevronLeft size={14} />}
                  disabled={versionIndex <= 0}
                  onClick={() => {
                    const patch = selectCanvasResultVersion(node.data, versionIndex - 1)
                    if (patch) updateNodeData(node.id, patch)
                  }}
                />
                <span>版本 {versionIndex + 1} / {history.length}</span>
                <Button
                  size="small"
                  type="text"
                  icon={<ChevronRight size={14} />}
                  disabled={versionIndex >= history.length - 1}
                  onClick={() => {
                    const patch = selectCanvasResultVersion(node.data, versionIndex + 1)
                    if (patch) updateNodeData(node.id, patch)
                  }}
                />
              </div>
            ) : null}

            <div className="canvas-inspector-actions">
              <Dropdown
                classNames={{ root: "canvas-popup canvas-branch-menu" }}
                trigger={["click"]}
                menu={{
                  items: [
                    { key: "right", label: "插入到右侧" },
                    { key: "down", label: "插入到下方" },
                  ],
                  onClick: ({ key }) => onInsertResult(node.id, key === "down" ? "down" : "right"),
                }}
              >
                <Button type="primary" icon={<Plus size={15} />}>
                  插入为{result.kind === "video" ? "视频" : "图片"}节点
                  <ChevronDown size={13} />
                </Button>
              </Dropdown>
              <Button
                icon={<Play size={15} />}
                onClick={() => onPreview({
                  url: result.url,
                  label: result.label || node.data.label,
                  kind: result.kind,
                })}
              >
                预览结果
              </Button>
            </div>
            {result.path ? (
              <dl className="canvas-inspector-meta">
                <dt>结果素材</dt>
                <dd>
                  <Typography.Text code copyable={{ text: result.path }} ellipsis>{result.path}</Typography.Text>
                </dd>
              </dl>
            ) : null}
          </div>
        </section>
      ) : null}
    </div>
  )
}

export function GeneratorOptionField({
  name, definition, value, disabled, onChange,
}: {
  name: string
  definition: CanvasOptionDefinition
  value: CanvasOptionValue | undefined
  disabled: boolean
  onChange: (name: string, value: CanvasOptionValue) => void
}) {
  const options = definition.ui_options?.map((item) => ({
    value: String(item.value),
    label: item.label,
    title: item.hint,
  })) ?? definition.enum?.map((item) => ({
    value: String(item),
    label: `${item}${definition.unit ? ` ${definition.unit}` : ""}`,
  })) ?? []
  const instanceId = useId()
  const fieldId = `canvas-generator-option-${name}-${instanceId}`

  return (
    <div className={`canvas-inspector-field${definition.type === "boolean" ? " is-inline" : ""}`}>
      <span className="canvas-inspector-field-label">
        {definition.label}{definition.unit ? `（${definition.unit}）` : ""}
      </span>
      {definition.type === "boolean" ? (
        <Switch
          id={fieldId}
          aria-label={definition.label}
          checked={Boolean(value)}
          disabled={disabled}
          onChange={(checked) => onChange(name, checked)}
        />
      ) : options.length ? (
        <Select
          classNames={{ popup: { root: "canvas-select-popup" } }}
          id={fieldId}
          aria-label={definition.label}
          className="w-full"
          value={value === undefined ? undefined : String(value)}
          options={options}
          disabled={disabled}
          onChange={(raw) => onChange(name, coerceOptionValue(definition, raw))}
        />
      ) : definition.type === "number" || definition.type === "integer" ? (
        <InputNumber
          id={fieldId}
          name={fieldId}
          aria-label={definition.label}
          className="w-full"
          value={typeof value === "number" ? value : value === undefined || value === "" ? null : Number(value)}
          min={definition.minimum}
          max={definition.maximum}
          step={definition.step}
          disabled={disabled}
          onChange={(next) => {
            if (next !== null) onChange(name, next)
          }}
        />
      ) : (
        <Input
          id={fieldId}
          name={fieldId}
          aria-label={definition.label}
          value={value === undefined ? "" : String(value)}
          pattern={definition.pattern}
          disabled={disabled}
          onChange={(event) => onChange(name, event.target.value)}
        />
      )}
      {definition.description ? <p className="canvas-inspector-hint">{definition.description}</p> : null}
    </div>
  )
}

function coerceOptionValue(definition: CanvasOptionDefinition, raw: string | number): CanvasOptionValue {
  if (definition.type === "number" || definition.type === "integer") return Number(raw)
  const matched = definition.ui_options?.find((item) => String(item.value) === String(raw))?.value
    ?? definition.enum?.find((item) => String(item) === String(raw))
  return matched !== undefined ? matched : String(raw)
}
