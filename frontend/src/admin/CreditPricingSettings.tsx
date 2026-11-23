import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Alert, Button, InputNumber, Modal, Popconfirm, Segmented, Space, Switch, Table, Tag, Tooltip, message } from "antd"
import { ApiRequestError, jsonMutation, requestJson } from "../api"
import { formatCredits, formatCny, MAX_CREDIT_AMOUNT, type CreditPriceRule } from "../credits/credits"
import {
  compactVariantLabels, isValidCreditPrice, MAX_VISIBLE_VARIANT_CHIPS,
  previewCallCost, previewCreditConversion, type BillingMode, type CallCostPreview,
} from "./credit-price"

const SCOPE_LABELS: Record<string, string> = {
  cloud_video: "云端视频", grs_image: "云端生图", llm: "LLM 大模型", vlm: "VLM 视觉模型",
}
const KIND_UNITS: Record<string, string> = { per_second: "秒", per_item: "张", per_call: "次" }
const muted = "text-[color:var(--studio-text-secondary)]"

type PriceMap = Record<string, number | null>
type PriceEdits = {
  enabled?: boolean
  unit_credits?: number | null
  unit_by_variant?: PriceMap
  extra_config?: Record<string, unknown>
}
type PriceDraft = PriceEdits & { expected_updated_at: string }
type ConversionDraft = {
  rule: CreditPriceRule
  baseExtra: Record<string, unknown>
  nativeUnit: string
  source: "native" | "manual"
  coefficient: number | null
  perUnit: number | null
  nativePrices: PriceMap
  manualPrices: PriceMap
  useManualSnapshot: boolean
  inputImagePrices: PriceMap
  freeQuota: number | null
}
type CostReferenceDraft = {
  rule: CreditPriceRule
  baseExtra: Record<string, unknown>
  inputPrice: number | null
  cachedPrice: number | null
  outputPrice: number | null
  inputTokens: number | null
  cachedTokens: number | null
  outputTokens: number | null
  coefficient: number | null
  estimated: boolean
  billingMode: BillingMode
  billingMargin: number | null
  minCredits: number | null
  offPeakEnabled: boolean
  offPeakDiscount: number | null
  offPeakStart: string
  offPeakEnd: string
  modelTiers: Array<{ model: string; inputPrice: number | null; cachedPrice: number | null; outputPrice: number | null }>
}
const COST_STATUS: Record<CallCostPreview["status"], { color: string; label: string }> = {
  below_cost: { color: "red", label: "低于成本" },
  thin: { color: "gold", label: "接近成本" },
  healthy: { color: "green", label: "有毛利" },
  unknown: { color: "default", label: "待校准" },
}

const priceMap = (value: unknown): PriceMap => value && typeof value === "object" && !Array.isArray(value)
  ? Object.fromEntries(Object.entries(value).map(([key, amount]) => [key, Number(amount)]))
  : {}
const readNumber = (value: unknown, fallback: number) => value === null ? null : Number(value ?? fallback)
const isNative = (config: Record<string, unknown>) => config.price_source !== "manual" && Object.keys(priceMap(config.native_variant_prices)).length > 0
const validMap = (values: PriceMap, integer = false) => Object.values(values).every((value) => isValidCreditPrice(value, integer))

function resolvedVariants(manual: PriceMap, extra: Record<string, unknown>): PriceMap {
  if (!isNative(extra)) return manual
  const perUnit = readNumber(extra.credits_per_native_unit, 0)
  const coefficient = readNumber(extra.provider_coefficient, 1)
  if (!perUnit) return manual
  const converted = Object.entries(priceMap(extra.native_variant_prices)).map(([key, value]) => [key, previewCreditConversion(value, perUnit, coefficient)])
  return { ...manual, ...Object.fromEntries(converted) }
}

export default function CreditPricingSettings({ csrfToken, active }: { csrfToken: string; active: boolean }) {
  const queryClient = useQueryClient()
  const [scope, setScope] = useState("")
  const [drafts, setDrafts] = useState<Record<string, PriceDraft>>({})
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [conversion, setConversion] = useState<ConversionDraft | null>(null)
  const [costReference, setCostReference] = useState<CostReferenceDraft | null>(null)
  const query = useQuery({
    queryKey: ["admin-credit-prices"],
    queryFn: ({ signal }) => requestJson<CreditPriceRule[]>("/api/admin/credits/prices", { signal }),
    enabled: active,
  })
  const mutation = useMutation({
    mutationFn: (rules: Array<PriceDraft & { rule_key: string }>) => requestJson<CreditPriceRule[]>(
      "/api/admin/credits/prices", jsonMutation(csrfToken, { rules }, "PUT"),
    ),
    onSuccess: (rules) => {
      queryClient.setQueryData(["admin-credit-prices"], rules)
      setDrafts({})
      message.success("价格已发布，对新提交生效")
      for (const key of ["modes", "canvas-modes", "credits-estimate", "pricing"]) {
        void queryClient.invalidateQueries({ queryKey: [key] })
      }
    },
    onError: (error) => {
      if (error instanceof ApiRequestError && error.status === 409) void query.refetch()
    },
  })

  const stage = (rule: CreditPriceRule, changes: PriceEdits) => {
    mutation.reset()
    setDrafts((current) => ({
      ...current,
      [rule.rule_key]: { ...current[rule.rule_key], ...changes, expected_updated_at: current[rule.rule_key]?.expected_updated_at ?? rule.updated_at },
    }))
  }
  const discard = (ruleKey: string) => {
    mutation.reset()
    setDrafts((current) => {
      const next = { ...current }
      delete next[ruleKey]
      return next
    })
  }
  const extraFor = (rule: CreditPriceRule) => drafts[rule.rule_key]?.extra_config ?? rule.extra_config ?? {}
  const variantsFor = (rule: CreditPriceRule) => drafts[rule.rule_key]?.unit_by_variant ?? rule.unit_by_variant ?? {}
  const staleDraft = (rule: CreditPriceRule) => Boolean(drafts[rule.rule_key] && drafts[rule.rule_key].expected_updated_at !== rule.updated_at)

  const costReferenceFor = (rule: CreditPriceRule): Record<string, unknown> | null => {
    const reference = extraFor(rule).cost_reference
    return reference && typeof reference === "object" && !Array.isArray(reference)
      ? reference as Record<string, unknown>
      : null
  }
  const costPreviewFor = (rule: CreditPriceRule): CallCostPreview | null => {
    const reference = costReferenceFor(rule)
    if (!reference) return null
    const extra = extraFor(rule)
    const unit = drafts[rule.rule_key]?.unit_credits ?? rule.unit_credits
    return previewCallCost(reference, unit, {
      billingMode: extra.billing_mode === "per_token" ? "per_token" : "per_call",
      billingMargin: readNumber(extra.billing_margin, 1),
      minCredits: readNumber(extra.min_credits, 1),
    })
  }
  const billingModeFor = (rule: CreditPriceRule): BillingMode => extraFor(rule).billing_mode === "per_token" ? "per_token" : "per_call"
  const openCostReference = (rule: CreditPriceRule) => {
    const reference = costReferenceFor(rule) ?? {}
    const extra = extraFor(rule)
    const offPeak = (reference.off_peak ?? {}) as Record<string, unknown>
    const windows = Array.isArray(offPeak.windows) ? offPeak.windows as Array<Record<string, unknown>> : []
    const tiers = reference.model_prices && typeof reference.model_prices === "object" && !Array.isArray(reference.model_prices)
      ? Object.entries(reference.model_prices as Record<string, Record<string, unknown>>).map(([model, tier]) => ({
        model,
        inputPrice: readNumber(tier.input_per_mtok, 1),
        cachedPrice: readNumber(tier.cached_input_per_mtok, 0.02),
        outputPrice: readNumber(tier.output_per_mtok, 4),
      }))
      : []
    setCostReference({
      rule,
      baseExtra: extra,
      inputPrice: readNumber(reference.input_per_mtok, 1),
      cachedPrice: readNumber(reference.cached_input_per_mtok, 0.02),
      outputPrice: readNumber(reference.output_per_mtok, 4),
      inputTokens: readNumber(reference.assumed_input_tokens, 6000),
      cachedTokens: readNumber(reference.assumed_cached_tokens, 0),
      outputTokens: readNumber(reference.assumed_output_tokens, 800),
      coefficient: readNumber(reference.provider_coefficient, 1),
      estimated: Boolean(reference.estimated ?? true),
      billingMode: extra.billing_mode === "per_token" ? "per_token" : "per_call",
      billingMargin: readNumber(extra.billing_margin, 1),
      minCredits: readNumber(extra.min_credits, 1),
      offPeakEnabled: Boolean(offPeak.enabled),
      offPeakDiscount: readNumber(offPeak.discount, 0.5),
      offPeakStart: String(windows[0]?.start ?? "00:30"),
      offPeakEnd: String(windows[0]?.end ?? "08:30"),
      modelTiers: tiers,
    })
  }
  const costReferencePreview = costReference
    ? previewCallCost({
      input_per_mtok: costReference.inputPrice ?? 0,
      cached_input_per_mtok: costReference.cachedPrice ?? 0,
      output_per_mtok: costReference.outputPrice ?? 0,
      assumed_input_tokens: costReference.inputTokens ?? 0,
      assumed_cached_tokens: costReference.cachedTokens ?? 0,
      assumed_output_tokens: costReference.outputTokens ?? 0,
      provider_coefficient: costReference.coefficient ?? 1,
    }, drafts[costReference.rule.rule_key]?.unit_credits ?? costReference.rule.unit_credits, {
      billingMode: costReference.billingMode,
      billingMargin: costReference.billingMargin,
      minCredits: costReference.minCredits,
    })
    : null
  const validTime = (value: string) => /^([01]\d|2[0-3]):[0-5]\d$/.test(value.trim())
  const costReferenceValid = Boolean(costReference
    && [costReference.inputPrice, costReference.cachedPrice, costReference.outputPrice,
      costReference.inputTokens, costReference.cachedTokens, costReference.outputTokens,
      costReference.coefficient, costReference.billingMargin, costReference.minCredits].every((value) => isValidCreditPrice(value))
    && costReference.minCredits !== null && Number.isInteger(costReference.minCredits) && costReference.minCredits >= 1
    && (costReference.billingMargin ?? 0) > 0
    && (costReference.inputTokens ?? 0) >= (costReference.cachedTokens ?? 0)
    && ((costReference.inputPrice ?? 0) > 0 || (costReference.outputPrice ?? 0) > 0)
    && (!costReference.offPeakEnabled || (validTime(costReference.offPeakStart) && validTime(costReference.offPeakEnd)
      && (costReference.offPeakDiscount ?? 1) > 0 && (costReference.offPeakDiscount ?? 0) <= 1))
    && costReference.modelTiers.every((tier) => tier.model.trim()
      && [tier.inputPrice, tier.cachedPrice, tier.outputPrice].every((value) => isValidCreditPrice(value))))
  const applyCostReference = () => {
    if (!costReference || !costReferenceValid) return
    const modelPrices = Object.fromEntries(costReference.modelTiers.map((tier) => [tier.model.trim(), {
      input_per_mtok: tier.inputPrice ?? 0,
      cached_input_per_mtok: tier.cachedPrice ?? 0,
      output_per_mtok: tier.outputPrice ?? 0,
    }]))
    stage(costReference.rule, {
      extra_config: {
        ...costReference.baseExtra,
        billing_mode: costReference.billingMode,
        billing_margin: costReference.billingMargin,
        min_credits: costReference.minCredits,
        cost_reference: {
          input_per_mtok: costReference.inputPrice,
          cached_input_per_mtok: costReference.cachedPrice,
          output_per_mtok: costReference.outputPrice,
          assumed_input_tokens: costReference.inputTokens,
          assumed_cached_tokens: costReference.cachedTokens,
          assumed_output_tokens: costReference.outputTokens,
          provider_coefficient: costReference.coefficient,
          estimated: costReference.estimated,
          reference_source: "manual",
          model_prices: modelPrices,
          off_peak: {
            enabled: costReference.offPeakEnabled,
            discount: costReference.offPeakDiscount,
            timezone: "Asia/Shanghai",
            windows: costReference.offPeakEnabled ? [{ start: costReference.offPeakStart.trim(), end: costReference.offPeakEnd.trim() }] : [],
          },
        },
      },
    })
    setCostReference(null)
  }

  const openConversion = (rule: CreditPriceRule) => {
    const extra = extraFor(rule)
    const manualPrices = variantsFor(rule)
    const nativePrices = priceMap(extra.native_variant_prices)
    const hasNative = Object.keys(nativePrices).length > 0
    const fromNative = isNative(extra)
    setConversion({
      rule,
      baseExtra: extra,
      nativeUnit: String(extra.native_unit ?? "rmb_per_second"),
      source: fromNative || !hasNative ? "native" : "manual",
      coefficient: readNumber(extra.provider_coefficient, 1),
      perUnit: readNumber(extra.credits_per_native_unit, 100),
      nativePrices: hasNative ? nativePrices : Object.fromEntries(Object.entries(manualPrices).map(([key, unit]) => [key, unit == null ? null : unit / 100])),
      manualPrices: fromNative ? resolvedVariants(manualPrices, extra) : manualPrices,
      useManualSnapshot: fromNative,
      inputImagePrices: priceMap(extra.input_image_price),
      freeQuota: readNumber(extra.input_image_free_quota, 0),
    })
  }

  const conversionValid = conversion && isValidCreditPrice(conversion.perUnit) && isValidCreditPrice(conversion.coefficient)
    && (conversion.source === "manual" || conversion.perUnit > 0)
    && isValidCreditPrice(conversion.freeQuota, true)
    && validMap(conversion.nativePrices) && validMap(conversion.inputImagePrices)
    && [...Object.values(conversion.nativePrices), ...Object.values(conversion.inputImagePrices)]
      .every((value) => previewCreditConversion(value, conversion.perUnit, conversion.coefficient) !== null)
    && (conversion.source === "native" || validMap(conversion.manualPrices, true))

  const stageConversion = () => {
    if (!conversion || !conversionValid) return
    const extra = {
      ...conversion.baseExtra,
      price_source: conversion.source,
      native_unit: conversion.nativeUnit,
      native_variant_prices: conversion.nativePrices,
      credits_per_native_unit: conversion.perUnit,
      provider_coefficient: conversion.coefficient,
      ...(Object.keys(conversion.inputImagePrices).length ? {
        input_image_price: conversion.inputImagePrices, input_image_free_quota: conversion.freeQuota,
      } : {}),
    }
    stage(conversion.rule, {
      extra_config: extra,
      ...(conversion.source === "manual" && conversion.useManualSnapshot ? { unit_by_variant: conversion.manualPrices } : {}),
    })
    setConversion(null)
  }

  const rules = query.data ?? []
  const scopes = [...new Set(rules.map((rule) => rule.scope))]
  const activeScope = scopes.includes(scope) ? scope : scopes[0]
  const visibleRules = rules.filter((rule) => rule.scope === activeScope)
  const draftCount = Object.keys(drafts).length
  const hasStaleDraft = rules.some(staleDraft)
  const invalidPrice = Object.values(drafts).some((draft) => (
    (draft.unit_credits !== undefined && !isValidCreditPrice(draft.unit_credits, true))
    || (draft.unit_by_variant && !validMap(draft.unit_by_variant, true))
    || (draft.extra_config && "grs_credits_to_platform" in draft.extra_config
      && !isValidCreditPrice(readNumber(draft.extra_config.grs_credits_to_platform, 0)))
  ))

  const renderUnit = (rule: CreditPriceRule) => {
    const draft = drafts[rule.rule_key]
    const disabled = mutation.isPending || staleDraft(rule)
    const extra = extraFor(rule)
    const unit = KIND_UNITS[rule.pricing_kind] ?? "次"
    if (rule.scope === "grs_image") {
      const ratio = readNumber(extra.grs_credits_to_platform, 0)
      const overrides = Object.keys(priceMap(extra.model_overrides)).length
      return (
        <div className="grid gap-1.5">
          <label className="flex items-center gap-2">
            <span>上游积分 ×</span>
            <InputNumber
              aria-label="GRS 生图换算系数"
              size="small" min={0} max={MAX_CREDIT_AMOUNT} step={0.1} controls={false}
              className="!w-24" value={ratio} disabled={disabled} status={ratio === null ? "error" : undefined}
              onChange={(value) => stage(rule, { extra_config: { ...extra, grs_credits_to_platform: value } })}
            />
          </label>
          <span className={`text-xs ${muted}`}>
            {ratio === null ? "请输入换算系数" : `例如上游 10 积分，计 ${formatCredits(Math.ceil(10 * ratio))} 平台积分/张`}
            {overrides ? ` · ${overrides} 个模型使用独立单价` : ""}
          </span>
        </div>
      )
    }
    const manual = variantsFor(rule)
    const native = isNative(extra)
    const entries = Object.entries(native ? resolvedVariants(manual, extra) : manual)
    if (!entries.length) {
      const value = draft?.unit_credits === undefined ? rule.unit_credits : draft.unit_credits
      const isCallRule = rule.scope === "llm" || rule.scope === "vlm"
      const preview = isCallRule ? costPreviewFor(rule) : null
      const status = preview ? COST_STATUS[preview.status] : null
      return (
        <div className="grid gap-1.5">
          <Space size={6}>
            <InputNumber
              aria-label={`${rule.rule_key} 积分单价`}
              size="small" controls={false} min={0} max={MAX_CREDIT_AMOUNT} precision={0}
              className="!w-24" value={value} disabled={disabled} status={value === null ? "error" : undefined}
              onChange={(next) => stage(rule, { unit_credits: next })}
            />
            <span className={`text-xs ${muted}`}>积分/{unit}</span>
            <span className="text-xs tabular-nums">≈ {formatCny((value ?? 0) / 100)}/{unit}</span>
          </Space>
          {isCallRule ? (
            <div className="flex flex-wrap items-center gap-2">
              {preview ? (
                <>
                  <Tag color={status?.color} className="!m-0">{status?.label}</Tag>
                  <Tag className="!m-0">{billingModeFor(rule) === "per_token" ? "按 token" : "按次"}</Tag>
                  <span className={`text-xs ${muted}`}>
                    成本 {formatCny(preview.costCny, 6)}/{unit} · 覆盖 {preview.coverage === null ? "—" : `${preview.coverage}×`}
                    {preview.tokenCredits !== null ? ` · 典型用量约 ${preview.tokenCredits} 积分` : ""}
                  </span>
                </>
              ) : (
                <span className={`text-xs ${muted}`}>未设置成本参考，无法判断是否倒贴</span>
              )}
              <Button type="link" size="small" disabled={disabled} onClick={() => openCostReference(rule)}>
                {preview ? "校准成本" : "设置成本参考"}
              </Button>
            </div>
          ) : null}
        </div>
      )
    }

    const labels = compactVariantLabels(entries.map(([variant]) => variant))
    const isExpanded = expanded[rule.rule_key]
    const visible = isExpanded ? entries : entries.slice(0, MAX_VISIBLE_VARIANT_CHIPS)
    return (
      <div className="grid gap-1.5">
        <div className="flex flex-wrap items-center gap-1.5">
          {visible.map(([variant, value], index) => (
            <Tooltip key={variant} title={variant}>
              <span className="inline-flex min-h-7 items-center gap-1.5 rounded-md border border-[color:var(--studio-border)] bg-[var(--studio-surface-raised)] px-2 text-xs tabular-nums">
                <span className={muted}>{labels[index]}</span>
                {native ? <strong>{formatCredits(value)}</strong> : (
                  <InputNumber
                    aria-label={`${rule.rule_key} ${variant} 积分单价`}
                    size="small" controls={false} min={0} max={MAX_CREDIT_AMOUNT} precision={0}
                    className="!w-[66px]" value={value} disabled={disabled} status={value === null ? "error" : undefined}
                    onChange={(next) => stage(rule, { unit_by_variant: { ...manual, [variant]: next } })}
                  />
                )}
              </span>
            </Tooltip>
          ))}
          {entries.length > MAX_VISIBLE_VARIANT_CHIPS ? (
            <Button size="small" type="text" onClick={() => setExpanded((current) => ({ ...current, [rule.rule_key]: !isExpanded }))}>
              {isExpanded ? "收起" : `另 ${entries.length - visible.length} 档`}
            </Button>
          ) : null}
        </div>
        <span className={`text-xs ${muted}`}>{native ? "原生价换算" : "手动单价"} · 积分/{unit}</span>
      </div>
    )
  }

  const nativeUnit = conversion?.nativeUnit === "official_credit_per_second" ? "官方积分" : "元"
  return (
    <>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        {scopes.length ? (
          <Segmented aria-label="价格分类" value={activeScope} onChange={setScope} options={scopes.map((key) => ({ value: key, label: SCOPE_LABELS[key] ?? key }))} />
        ) : <span />}
        <Space>
          {draftCount ? (
            <Popconfirm title="放弃所有未发布的价格修改？" okText="放弃修改" cancelText="继续编辑" onConfirm={() => { setDrafts({}); mutation.reset() }}>
              <Button disabled={mutation.isPending}>放弃修改</Button>
            </Popconfirm>
          ) : null}
          <Button
            type="primary"
            loading={mutation.isPending}
            disabled={!draftCount || invalidPrice || hasStaleDraft || query.isFetching}
            onClick={() => mutation.mutate(Object.entries(drafts).map(([rule_key, draft]) => ({ rule_key, ...draft })))}
          >
            发布修改{draftCount ? `（${draftCount}）` : ""}
          </Button>
        </Space>
      </div>
      <p className={`mb-3 text-xs ${muted}`}>发布后，新提交按更新后的单价计费。停用规则后，该条目免扣积分。</p>
      {activeScope === "llm" || activeScope === "vlm" ? (
        <p className={`mb-3 text-xs ${muted}`}>
          按次计费统一按 <strong>100 积分 = 1 元</strong> 换算约人民币。任何「成本参考」只用于核对上游 token 成本与毛利，不参与实际结算。
        </p>
      ) : null}
      {query.isError ? <Alert className="mb-3" type="error" showIcon title={query.error.message} action={<Button size="small" onClick={() => void query.refetch()}>重新加载</Button>} /> : null}
      {mutation.isError ? <Alert className="mb-3" type="error" showIcon title={mutation.error.message} /> : null}
      {hasStaleDraft ? <Alert className="mb-3" type="warning" showIcon title="部分规则已被其他操作更新。撤销冲突条目的修改后，可继续发布其余修改。" /> : null}
      <Table<CreditPriceRule>
        rowKey="rule_key"
        size="middle"
        loading={query.isFetching}
        dataSource={visibleRules}
        locale={{ emptyText: query.isError ? "价格加载失败" : "暂无计价规则" }}
        pagination={false}
        scroll={{ x: 930 }}
        columns={[
          {
            title: "计价条目", width: 385,
            render: (_, rule) => (
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="break-all font-mono text-xs font-medium">{rule.rule_key}</span>
                  {drafts[rule.rule_key] ? <Tag color={staleDraft(rule) ? "red" : "gold"} className="!m-0">{staleDraft(rule) ? "版本冲突" : "待发布"}</Tag> : null}
                </div>
                {rule.note ? <Tooltip title={rule.note}><p className={`mt-1 line-clamp-1 text-xs ${muted}`}>{rule.note}</p></Tooltip> : null}
              </div>
            ),
          },
          { title: "计费单价", width: 425, render: (_, rule) => renderUnit(rule) },
          {
            title: "计费状态", width: 112,
            render: (_, rule) => {
              const enabled = drafts[rule.rule_key]?.enabled ?? rule.enabled
              return <Space size={7}><Switch size="small" aria-label={`${rule.rule_key} 计费`} checked={enabled} disabled={mutation.isPending || staleDraft(rule)} onChange={(checked) => stage(rule, { enabled: checked })} /><span className={`text-xs ${muted}`}>{enabled ? "启用" : "停用"}</span></Space>
            },
          },
          {
            title: "操作", width: 142,
            render: (_, rule) => {
              const hasVariants = rule.pricing_kind === "per_second" && Object.keys(variantsFor(rule)).length > 0
              return (
                <Space size={2}>
                  {hasVariants ? <Button type="link" size="small" disabled={mutation.isPending || staleDraft(rule)} onClick={() => openConversion(rule)}>换算设置</Button> : null}
                  {drafts[rule.rule_key] ? <Button type="link" size="small" disabled={mutation.isPending} onClick={() => discard(rule.rule_key)}>撤销</Button> : null}
                </Space>
              )
            },
          },
        ]}
      />

      <Modal
        open={conversion !== null}
        title="视频积分换算"
        onCancel={() => setConversion(null)}
        onOk={stageConversion}
        okText="应用到待发布修改"
        cancelText="取消"
        okButtonProps={{ disabled: !conversionValid }}
        width={700}
        destroyOnHidden
      >
        {conversion ? (
          <div className="grid gap-4">
            <p className={`font-mono text-xs ${muted}`}>{conversion.rule.rule_key}</p>
            <Segmented<"native" | "manual">
              aria-label="计价来源"
              value={conversion.source}
              onChange={(source) => setConversion({ ...conversion, source })}
              options={[{ value: "native", label: "原生价换算" }, { value: "manual", label: "手动单价" }]}
            />
            <div className="flex flex-wrap items-end gap-4">
              <label className="grid gap-1.5 text-sm">
                <span>每{nativeUnit}兑换积分</span>
                <InputNumber min={0} max={MAX_CREDIT_AMOUNT} value={conversion.perUnit} onChange={(perUnit) => setConversion({ ...conversion, perUnit })} />
              </label>
              <label className="grid gap-1.5 text-sm">
                <span>供应商系数</span>
                <InputNumber min={0} max={MAX_CREDIT_AMOUNT} step={0.1} value={conversion.coefficient} onChange={(coefficient) => setConversion({ ...conversion, coefficient })} />
              </label>
            </div>
            <p className={`text-xs ${muted}`}>
              {conversion.source === "native" ? "原生价 × 兑换积分 × 供应商系数，向上取整。" : "视频按表中的平台单价计费，应用后可在价格表逐档修改。参考图费仍按换算设置计算。"}
            </p>
            <Table
              rowKey="key" size="small" pagination={false}
              dataSource={Object.entries(conversion.nativePrices).map(([key, value]) => ({ key, value }))}
              columns={[
                { title: "档位", dataIndex: "key" },
                {
                  title: `原生价（${nativeUnit}/秒）`,
                  render: (_, row) => <InputNumber aria-label={`${row.key} 原生价`} min={0} max={MAX_CREDIT_AMOUNT} step={0.01} value={row.value} onChange={(value) => setConversion({ ...conversion, nativePrices: { ...conversion.nativePrices, [row.key]: value } })} />,
                },
                {
                  title: "平台单价（积分/秒）", align: "right",
                  render: (_, row) => <span className="tabular-nums font-medium">{formatCredits(conversion.source === "manual" ? conversion.manualPrices[row.key] : previewCreditConversion(row.value, conversion.perUnit, conversion.coefficient))}</span>,
                },
              ]}
            />
            {Object.keys(conversion.inputImagePrices).length ? (
              <div className="grid gap-2">
                <label className="flex items-center gap-2 text-sm">
                  <span>每任务免费参考图</span>
                  <InputNumber className="!w-20" min={0} max={MAX_CREDIT_AMOUNT} precision={0} value={conversion.freeQuota} onChange={(freeQuota) => setConversion({ ...conversion, freeQuota })} />
                  <span>张</span>
                </label>
                <Table
                  rowKey="key" size="small" pagination={false}
                  dataSource={Object.entries(conversion.inputImagePrices).map(([key, value]) => ({ key, value }))}
                  columns={[
                    { title: "模型档位", dataIndex: "key" },
                    {
                      title: `超额原生价（${nativeUnit}/张）`,
                      render: (_, row) => <InputNumber aria-label={`${row.key} 参考图原生价`} min={0} max={MAX_CREDIT_AMOUNT} step={0.01} value={row.value} onChange={(value) => setConversion({ ...conversion, inputImagePrices: { ...conversion.inputImagePrices, [row.key]: value } })} />,
                    },
                    {
                      title: "超额单价（积分/张）", align: "right",
                      render: (_, row) => <span className="tabular-nums font-medium">{formatCredits(previewCreditConversion(row.value, conversion.perUnit, conversion.coefficient))}</span>,
                    },
                  ]}
                />
              </div>
            ) : null}
            {!conversionValid ? <Alert type="warning" showIcon title="请填写有效单价、换算系数和免费张数，原生价换算的兑换比例须大于 0。" /> : null}
          </div>
        ) : null}
      </Modal>

      <Modal
        open={costReference !== null}
        title="LLM / VLM 成本参考"
        onCancel={() => setCostReference(null)}
        onOk={applyCostReference}
        okText="应用到待发布修改"
        cancelText="取消"
        okButtonProps={{ disabled: !costReferenceValid }}
        width={760}
        destroyOnHidden
      >
        {costReference ? (
          <div className="grid gap-4">
            <p className={`font-mono text-xs ${muted}`}>{costReference.rule.rule_key}</p>
            <p className={`text-xs ${muted}`}>
              成本参考默认只用于核对毛利；切换到「按 token」后，实际扣费改为按真实 usage 结算，未采集到 usage 时回退按次单价。
            </p>
            <div className="flex flex-wrap items-end gap-4 rounded-lg border border-[color:var(--studio-border)] p-3">
              <label className="grid gap-1 text-xs">
                <span>结算方式</span>
                <Segmented
                  size="small"
                  value={costReference.billingMode}
                  onChange={(value) => setCostReference({ ...costReference, billingMode: value as BillingMode })}
                  options={[{ label: "按次（默认）", value: "per_call" }, { label: "按 token", value: "per_token" }]}
                />
              </label>
              <label className="grid gap-1 text-xs">
                <span>加价系数（计入积分）</span>
                <InputNumber aria-label="结算加价系数" min={0} step={0.1} value={costReference.billingMargin} onChange={(value) => setCostReference({ ...costReference, billingMargin: value })} />
              </label>
              <label className="grid gap-1 text-xs">
                <span>最低积分/次</span>
                <InputNumber aria-label="最低积分" min={1} precision={0} value={costReference.minCredits} onChange={(value) => setCostReference({ ...costReference, minCredits: value })} />
              </label>
            </div>
            <div className="grid gap-2">
              <div className="flex items-center justify-between">
                <strong className="text-sm">模型档位（留空则用基础价）</strong>
                <Button size="small" onClick={() => setCostReference({ ...costReference, modelTiers: [...costReference.modelTiers, { model: "", inputPrice: 1, cachedPrice: 0.02, outputPrice: 4 }] })}>添加模型</Button>
              </div>
              {costReference.modelTiers.map((tier, index) => (
                <div key={index} className="grid grid-cols-[1.4fr_1fr_1fr_1fr_auto] items-end gap-2">
                  <label className="grid gap-1 text-xs">
                    <span>模型 ID</span>
                    <input
                      aria-label={`模型 ${index + 1} ID`}
                      className="h-8 w-full rounded border border-[color:var(--studio-border)] bg-transparent px-2 text-sm"
                      value={tier.model}
                      placeholder="deepseek-v4-flash"
                      onChange={(event) => setCostReference({ ...costReference, modelTiers: costReference.modelTiers.map((item, i) => i === index ? { ...item, model: event.target.value } : item) })}
                    />
                  </label>
                  <label className="grid gap-1 text-xs">
                    <span>输入</span>
                    <InputNumber aria-label={`模型 ${index + 1} 输入价`} min={0} step={0.01} value={tier.inputPrice} onChange={(value) => setCostReference({ ...costReference, modelTiers: costReference.modelTiers.map((item, i) => i === index ? { ...item, inputPrice: value } : item) })} />
                  </label>
                  <label className="grid gap-1 text-xs">
                    <span>缓存</span>
                    <InputNumber aria-label={`模型 ${index + 1} 缓存价`} min={0} step={0.01} value={tier.cachedPrice} onChange={(value) => setCostReference({ ...costReference, modelTiers: costReference.modelTiers.map((item, i) => i === index ? { ...item, cachedPrice: value } : item) })} />
                  </label>
                  <label className="grid gap-1 text-xs">
                    <span>输出</span>
                    <InputNumber aria-label={`模型 ${index + 1} 输出价`} min={0} step={0.01} value={tier.outputPrice} onChange={(value) => setCostReference({ ...costReference, modelTiers: costReference.modelTiers.map((item, i) => i === index ? { ...item, outputPrice: value } : item) })} />
                  </label>
                  <Button size="small" danger onClick={() => setCostReference({ ...costReference, modelTiers: costReference.modelTiers.filter((_, i) => i !== index) })}>删除</Button>
                </div>
              ))}
            </div>
            <div className="flex flex-wrap items-end gap-4 rounded-lg border border-[color:var(--studio-border)] p-3">
              <label className="flex items-center gap-2 text-xs">
                <Switch size="small" checked={costReference.offPeakEnabled} onChange={(offPeakEnabled) => setCostReference({ ...costReference, offPeakEnabled })} />
                <span>启用错峰折扣（Asia/Shanghai）</span>
              </label>
              <label className="grid gap-1 text-xs">
                <span>折扣系数</span>
                <InputNumber aria-label="错峰折扣" min={0.01} max={1} step={0.05} value={costReference.offPeakDiscount} onChange={(value) => setCostReference({ ...costReference, offPeakDiscount: value })} />
              </label>
              <label className="grid gap-1 text-xs">
                <span>开始 HH:MM</span>
                <input aria-label="错峰开始" className="h-8 w-24 rounded border border-[color:var(--studio-border)] bg-transparent px-2 font-mono text-sm" value={costReference.offPeakStart} onChange={(event) => setCostReference({ ...costReference, offPeakStart: event.target.value })} />
              </label>
              <label className="grid gap-1 text-xs">
                <span>结束 HH:MM</span>
                <input aria-label="错峰结束" className="h-8 w-24 rounded border border-[color:var(--studio-border)] bg-transparent px-2 font-mono text-sm" value={costReference.offPeakEnd} onChange={(event) => setCostReference({ ...costReference, offPeakEnd: event.target.value })} />
              </label>
            </div>
            <div className="grid gap-2">
              <strong className="text-sm">上游单价（元 / 百万 tokens）</strong>
              <div className="grid grid-cols-3 gap-3">
                <label className="grid gap-1 text-xs">
                  <span>输入</span>
                  <InputNumber aria-label="输入单价" min={0} step={0.01} value={costReference.inputPrice} onChange={(value) => setCostReference({ ...costReference, inputPrice: value })} />
                </label>
                <label className="grid gap-1 text-xs">
                  <span>输入（缓存命中）</span>
                  <InputNumber aria-label="缓存命中单价" min={0} step={0.01} value={costReference.cachedPrice} onChange={(value) => setCostReference({ ...costReference, cachedPrice: value })} />
                </label>
                <label className="grid gap-1 text-xs">
                  <span>输出</span>
                  <InputNumber aria-label="输出单价" min={0} step={0.01} value={costReference.outputPrice} onChange={(value) => setCostReference({ ...costReference, outputPrice: value })} />
                </label>
              </div>
            </div>
            <div className="grid gap-2">
              <strong className="text-sm">典型单次用量（tokens）</strong>
              <div className="grid grid-cols-3 gap-3">
                <label className="grid gap-1 text-xs">
                  <span>输入</span>
                  <InputNumber aria-label="典型输入 tokens" min={0} precision={0} step={1000} value={costReference.inputTokens} onChange={(value) => setCostReference({ ...costReference, inputTokens: value })} />
                </label>
                <label className="grid gap-1 text-xs">
                  <span>其中缓存命中</span>
                  <InputNumber aria-label="典型缓存 tokens" min={0} precision={0} step={1000} value={costReference.cachedTokens} onChange={(value) => setCostReference({ ...costReference, cachedTokens: value })} />
                </label>
                <label className="grid gap-1 text-xs">
                  <span>输出</span>
                  <InputNumber aria-label="典型输出 tokens" min={0} precision={0} step={500} value={costReference.outputTokens} onChange={(value) => setCostReference({ ...costReference, outputTokens: value })} />
                </label>
              </div>
            </div>
            <div className="flex flex-wrap items-end gap-4">
              <label className="grid gap-1 text-xs">
                <span>供应商成本系数（1.0 = 官方价）</span>
                <InputNumber aria-label="加价系数" min={0} step={0.1} value={costReference.coefficient} onChange={(value) => setCostReference({ ...costReference, coefficient: value })} />
              </label>
              <label className="flex items-center gap-2 text-xs">
                <Switch size="small" checked={costReference.estimated} onChange={(estimated) => setCostReference({ ...costReference, estimated })} />
                <span>tokens 为估算值（未采集真实用量时按此估算）</span>
              </label>
            </div>
            {costReferencePreview ? (
              <div className="rounded-lg border border-[color:var(--studio-border)] bg-[var(--studio-surface-raised)] p-3 text-sm">
                <Space size={16} wrap>
                  <span>单次成本 <strong className="tabular-nums">{formatCny(costReferencePreview.costCny, 6)}</strong></span>
                  <span>当前扣费 <strong className="tabular-nums">{formatCny(costReferencePreview.billedCny, 6)}</strong>（{(drafts[costReference.rule.rule_key]?.unit_credits ?? costReference.rule.unit_credits)} 积分）</span>
                  <span>覆盖率 <strong className="tabular-nums">{costReferencePreview.coverage === null ? "—" : `${costReferencePreview.coverage}×`}</strong></span>
                  <Tag color={COST_STATUS[costReferencePreview.status].color}>{COST_STATUS[costReferencePreview.status].label}</Tag>
                  <span className={muted}>建议 {costReferencePreview.suggestedUnitCredits} 积分/次</span>
                  {costReferencePreview.tokenCredits !== null ? (
                    <span className={muted}>按典型用量 ≈ {costReferencePreview.tokenCredits} 积分/次</span>
                  ) : null}
                </Space>
              </div>
            ) : null}
            {!costReferenceValid ? <Alert type="warning" showIcon title="请填写有效的非负单价和 tokens；缓存命中不能大于输入，输入或输出单价至少有一个大于 0。" /> : null}
            {costReference.estimated ? <p className={`text-xs ${muted}`}>实际调用若已采集 usage，流水会按真实 tokens 重算；未采集时按这里的典型用量估算，并在流水标注「估算」。</p> : null}
          </div>
        ) : null}
      </Modal>
    </>
  )
}
