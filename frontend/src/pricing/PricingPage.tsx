import { useEffect, useMemo, useState, type CSSProperties, type KeyboardEvent } from "react"
import { useQuery } from "@tanstack/react-query"
import { Alert, Button, InputNumber, Segmented, Select, Slider, Table, Tag, Tooltip } from "antd"
import {
  ArrowUpRight,
  Bot,
  CheckCircle2,
  Clock3,
  Coins,
  Cpu,
  ImagePlus,
  Images,
  Info,
  MousePointerClick,
  RefreshCw,
  Sparkles,
  WalletCards,
} from "lucide-react"
import { useNavigate } from "react-router-dom"
import { requestJson } from "../api"
import { formatCredits } from "../credits/credits"
import { PATHS } from "../paths"
import {
  creditsToYuan,
  durationBounds,
  quotePricing,
  type PricingAiCall,
  type PricingAiCalls,
  type PricingCatalog,
  type PricingImageGeneration,
  type PricingModel,
  type PricingProvider,
  type PricingResolution,
} from "./pricing-model"

const PROVIDER_ACCENTS: Record<string, string> = {
  grs: "#0ea5a4",
  "grs-agnes": "#0891b2",
  "grs-wan": "#7c3aed",
  minimax: "#7047f6",
}

function providerAccent(key: string) {
  return PROVIDER_ACCENTS[key] ?? "var(--studio-primary)"
}

function InputImageNote({ provider, model }: { provider: PricingProvider; model: PricingModel }) {
  if (model.input_image_credits > 0) {
    return (
      <p className="mt-3 flex items-start gap-2 text-xs leading-5 text-[var(--studio-text-muted)]">
        <ImagePlus size={14} className="mt-0.5 shrink-0" aria-hidden />
        输入图片：每任务前 {provider.input_image_free_quota} 张免费，超出部分{" "}
        <strong className="font-medium text-[var(--studio-text-secondary)]">{model.input_image_credits} 积分/张</strong>。
      </p>
    )
  }
  return (
    <p className="mt-3 flex items-start gap-2 text-xs leading-5 text-[var(--studio-text-muted)]">
      <ImagePlus size={14} className="mt-0.5 shrink-0" aria-hidden />
      输入图片：每任务前 {provider.input_image_free_quota} 张免费，当前不额外收费。
    </p>
  )
}

function ModelCard({
  provider,
  model,
  selected,
  onSelect,
}: {
  provider: PricingProvider
  model: PricingModel
  selected: boolean
  onSelect: () => void
}) {
  const accent = providerAccent(provider.key)
  const handleKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault()
      onSelect()
    }
  }
  const columns = [
    {
      title: "分辨率",
      dataIndex: "value",
      key: "value",
      render: (value: string) => <Tag className="!m-0">{value}</Tag>,
    },
    {
      title: "每秒积分",
      dataIndex: "credits_per_second",
      key: "credits_per_second",
      align: "right" as const,
      render: (value: number) => <strong className="tabular-nums font-semibold">{value}</strong>,
    },
    {
      title: "5 秒",
      dataIndex: "credits_5s",
      key: "credits_5s",
      align: "right" as const,
      render: (value: number) => <span className="tabular-nums">{formatCredits(value)} 积分</span>,
    },
    {
      title: "10 秒",
      dataIndex: "credits_10s",
      key: "credits_10s",
      align: "right" as const,
      render: (value: number) => <span className="tabular-nums">{formatCredits(value)} 积分</span>,
    },
    {
      title: "官方价",
      dataIndex: "native_price_per_second",
      key: "native_price_per_second",
      align: "right" as const,
      render: (value: number | null | undefined) => (
        <span className="tabular-nums text-[var(--studio-text-muted)]">
          {typeof value === "number" ? `¥${value.toFixed(2)}/秒` : "—"}
        </span>
      ),
    },
  ]
  return (
    <section
      aria-label={`${provider.label} ${model.label} 价格`}
      className={`pricing-model-card rounded-2xl border bg-[var(--studio-surface)] p-5${selected ? " is-selected" : ""}`}
      style={{ "--pricing-accent": accent } as CSSProperties}
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      onClick={onSelect}
      onKeyDown={handleKeyDown}
    >
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-base font-semibold text-[var(--studio-text)]">{model.label}</h3>
            <Tag color="purple" className="!m-0">{model.tagline}</Tag>
            {model.resolutions.some((item) => item.value === "2K") ? (
              <Tag color="gold" className="!m-0">2K</Tag>
            ) : null}
          </div>
          <p className="mt-1 text-xs leading-5 text-[var(--studio-text-muted)]">{model.description}</p>
        </div>
        <Button
          size="small"
          type={selected ? "primary" : "default"}
          ghost={!selected}
          icon={selected ? <CheckCircle2 size={14} /> : undefined}
          onClick={(event) => {
            event.stopPropagation()
            onSelect()
          }}
        >
          {selected ? "当前方案" : "按此估算"}
        </Button>
      </header>
      <Table<PricingResolution>
        className="pricing-table mt-3"
        rowKey="value"
        size="small"
        pagination={false}
        showHeader
        dataSource={model.resolutions}
        columns={columns}
      />
      <InputImageNote provider={provider} model={model} />
    </section>
  )
}

function PricingCalculator({
  catalog,
  provider,
  model,
  resolution,
  duration,
  referenceCount,
  onDurationChange,
  onReferenceChange,
  onModelChange,
  onResolutionChange,
}: {
  catalog: PricingCatalog
  provider: PricingProvider
  model: PricingModel
  resolution: PricingResolution
  duration: number
  referenceCount: number
  onDurationChange: (value: number) => void
  onReferenceChange: (value: number) => void
  onModelChange: (value: string) => void
  onResolutionChange: (value: string) => void
}) {
  const navigate = useNavigate()
  const bounds = durationBounds(provider.key, model.key, resolution.value)
  const quote = quotePricing(
    model,
    resolution,
    duration,
    referenceCount,
    provider.input_image_free_quota,
    catalog.credits_per_yuan,
  )
  const accent = providerAccent(provider.key)
  return (
    <aside className="rounded-2xl border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5 lg:sticky lg:top-24">
      <div className="flex items-center gap-2">
        <span className="grid size-9 place-items-center rounded-xl" style={{ background: `${accent}18`, color: accent }}>
          <WalletCards size={18} aria-hidden />
        </span>
        <div>
          <h2 className="text-base font-semibold text-[var(--studio-text)]">价格试算</h2>
          <p className="text-[11px] text-[var(--studio-text-muted)]">按当前档位估算，实际以提交时预扣为准</p>
        </div>
      </div>

      <div className="mt-4 grid gap-3">
        <label className="grid gap-1.5">
          <span className="text-xs text-[var(--studio-text-secondary)]">模型档位</span>
          <Select
            value={model.key}
            onChange={onModelChange}
            options={provider.models.map((item) => ({
              value: item.key,
              label: `${item.label} · ${item.tagline}`,
            }))}
          />
        </label>
        <label className="grid gap-1.5">
          <span className="text-xs text-[var(--studio-text-secondary)]">分辨率</span>
          <Segmented
            block
            value={resolution.value}
            onChange={(value) => onResolutionChange(String(value))}
            options={model.resolutions.map((item) => ({ value: item.value, label: item.label }))}
          />
        </label>
        <label className="grid gap-1.5">
          <span className="flex items-center justify-between text-xs text-[var(--studio-text-secondary)]">
            <span>时长</span>
            <span className="tabular-nums text-[var(--studio-text-muted)]">{duration} 秒</span>
          </span>
          <Slider
            min={bounds.min}
            max={bounds.max}
            step={1}
            value={duration}
            onChange={(value) => onDurationChange(Number(value))}
            tooltip={{ formatter: (value) => `${value} 秒` }}
          />
        </label>
        <label className="grid gap-1.5">
          <span className="flex items-center justify-between text-xs text-[var(--studio-text-secondary)]">
            <span>参考图</span>
            <span className="text-[var(--studio-text-muted)]">每任务前 {provider.input_image_free_quota} 张免费</span>
          </span>
          <InputNumber
            min={0}
            max={9}
            value={referenceCount}
            onChange={(value) => onReferenceChange(Number(value ?? 0))}
            className="w-full"
            addonAfter="张"
          />
        </label>
      </div>

      <div className="mt-4 rounded-xl bg-[var(--studio-surface-raised)] p-4">
        <div className="flex items-end justify-between gap-3">
          <div>
            <p className="text-xs text-[var(--studio-text-muted)]">预计消耗</p>
            <p className="mt-1 text-3xl font-semibold tabular-nums text-[var(--studio-text)]">
              {formatCredits(quote.totalCredits)}
              <span className="ml-1 text-sm font-normal text-[var(--studio-text-muted)]">积分</span>
            </p>
          </div>
          <p className="text-sm tabular-nums text-[var(--studio-text-muted)]">≈ ¥{quote.yuan.toFixed(2)}</p>
        </div>
        <ul className="mt-3 grid gap-1 text-xs leading-5 text-[var(--studio-text-muted)]">
          <li className="flex items-center justify-between gap-3">
            <span>{duration} 秒 × {resolution.credits_per_second} 积分/秒</span>
            <span className="tabular-nums">{formatCredits(quote.secondsCredits)} 积分</span>
          </li>
          {quote.inputImageCount > 0 ? (
            <li className="flex items-center justify-between gap-3">
              <span>参考图超出 {quote.inputImageCount} 张 × {model.input_image_credits} 积分</span>
              <span className="tabular-nums">{formatCredits(quote.inputImageCredits)} 积分</span>
            </li>
          ) : (
            <li className="flex items-center justify-between gap-3">
              <span>参考图在免费额度内</span>
              <span className="tabular-nums">0 积分</span>
            </li>
          )}
        </ul>
      </div>

      <Button
        type="primary"
        size="large"
        block
        className="mt-4"
        icon={<ArrowUpRight size={16} />}
        disabled={!provider.available}
        onClick={() => navigate(`${PATHS.generateVideo}?workflow=${encodeURIComponent(provider.workflow_ids[0] ?? "")}`)}
      >
        用这个配置去生成
      </Button>
      <p className="mt-3 flex items-start gap-1.5 text-[11px] leading-5 text-[var(--studio-text-subtle)]">
        <Info size={12} className="mt-0.5 shrink-0" aria-hidden />
        任务提交时预扣积分，失败自动全额退回；余额不足时无法提交。
      </p>
    </aside>
  )
}

function ImagePricingSection({
  data,
  creditsPerYuan,
}: {
  data: PricingImageGeneration
  creditsPerYuan: number
}) {
  if (!data.models.length) return null
  return (
    <section id="image-pricing" className="mt-10 scroll-mt-24">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="grid size-8 place-items-center rounded-lg bg-[var(--studio-primary-soft)] text-[var(--studio-primary)]">
              <Images size={16} aria-hidden />
            </span>
            <h2 className="text-xl font-semibold text-[var(--studio-text)]">生图价格</h2>
          </div>
          <p className="mt-1 max-w-[760px] text-sm leading-6 text-[var(--studio-text-secondary)]">
            图片服务模型按张计费，单价来自平台价格表并随上游调价更新；提交时预扣，任务失败自动全额退回。
          </p>
        </div>
        <Tag color="cyan" className="!m-0">按张计费</Tag>
      </header>
      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {data.models.map((model) => (
          <article
            key={model.key}
            className="flex flex-col rounded-2xl border border-[var(--studio-border)] bg-[var(--studio-surface)] p-4"
          >
            <div className="flex items-start justify-between gap-2">
              <h3 className="text-sm font-semibold text-[var(--studio-text)]">{model.label}</h3>
              {model.is_default ? <Tag color="purple" className="!m-0">默认</Tag> : null}
            </div>
            <p className="mt-1 flex-1 text-xs leading-5 text-[var(--studio-text-muted)]">
              {model.description || "按张计费，规格以创作页为准。"}
            </p>
            <div className="mt-3 flex items-baseline gap-1.5 border-t border-[var(--studio-border)] pt-3">
              <span className="text-2xl font-semibold tabular-nums text-[var(--studio-text)]">
                {formatCredits(model.credits_per_image)}
              </span>
              <span className="text-xs text-[var(--studio-text-muted)]">积分/张</span>
              <span className="ml-auto text-xs tabular-nums text-[var(--studio-text-muted)]">
                ≈ ¥{creditsToYuan(model.credits_per_image, creditsPerYuan).toFixed(2)}
              </span>
            </div>
          </article>
        ))}
      </div>
      <p className="mt-3 flex items-start gap-1.5 text-xs leading-5 text-[var(--studio-text-subtle)]">
        <Info size={12} className="mt-0.5 shrink-0" aria-hidden />
        局部重绘、消除笔、扩图等复合图片工作流不额外计费；0 积分表示当前价格表为免费口径。
      </p>
    </section>
  )
}

const AI_SCOPE_LABELS: Record<PricingAiCall["scope"], string> = {
  llm: "文本大模型",
  vlm: "视觉理解",
}

function AiCallPricingSection({
  data,
  creditsPerYuan,
}: {
  data: PricingAiCalls
  creditsPerYuan: number
}) {
  if (!data.items.length) return null
  const columns = [
    {
      title: "功能",
      dataIndex: "label",
      key: "label",
      render: (_: string, item: PricingAiCall) => {
        // 价格表 note 形如「提示词优化（每次）」；去掉已作为标题的功能名，只留计费口径。
        const detail = item.description
          .replace(item.label, "")
          .trim()
          .replace(/^[（(]\s*/, "")
          .replace(/\s*[）)]$/, "")
        return (
          <div className="min-w-0">
            <p className="text-sm font-medium text-[var(--studio-text)]">{item.label}</p>
            {detail ? (
              <p className="mt-0.5 text-xs leading-5 text-[var(--studio-text-muted)]">{detail}</p>
            ) : null}
          </div>
        )
      },
    },
    {
      title: "类型",
      dataIndex: "scope",
      key: "scope",
      render: (scope: PricingAiCall["scope"]) => (
        <Tag color={scope === "vlm" ? "geekblue" : "blue"} className="!m-0">
          {AI_SCOPE_LABELS[scope] ?? scope}
        </Tag>
      ),
    },
    {
      title: "计费方式",
      dataIndex: "billing_mode",
      key: "billing_mode",
      render: (mode: PricingAiCall["billing_mode"]) => (
        <span className="text-xs text-[var(--studio-text-secondary)]">
          {mode === "per_token" ? "按 token 估算" : "按次"}
        </span>
      ),
    },
    {
      title: "单次积分",
      dataIndex: "unit_credits",
      key: "unit_credits",
      align: "right" as const,
      render: (value: number, item: PricingAiCall) => (
        <span className="tabular-nums">
          {formatCredits(value)} 积分
          {item.billing_mode === "per_token" ? (
            <span className="ml-1 text-xs text-[var(--studio-text-muted)]">（典型用量）</span>
          ) : null}
        </span>
      ),
    },
    {
      title: "折合",
      dataIndex: "unit_credits",
      key: "yuan",
      align: "right" as const,
      render: (value: number) => (
        <span className="tabular-nums text-[var(--studio-text-muted)]">
          ≈ ¥{creditsToYuan(value, creditsPerYuan).toFixed(2)}
        </span>
      ),
    },
  ]
  return (
    <section id="ai-pricing" className="mt-10 scroll-mt-24">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="grid size-8 place-items-center rounded-lg bg-[var(--studio-primary-soft)] text-[var(--studio-primary)]">
              <Bot size={16} aria-hidden />
            </span>
            <h2 className="text-xl font-semibold text-[var(--studio-text)]">AI 大模型价格</h2>
          </div>
          <p className="mt-1 max-w-[760px] text-sm leading-6 text-[var(--studio-text-secondary)]">
            写作、拆解、反推与对话等功能调用大模型时按次或按 token 计费；下表为当前价格表的实际生效价。
          </p>
        </div>
        <Tag color="blue" className="!m-0">按次 / 按 token</Tag>
      </header>
      <div className="mt-4 overflow-hidden rounded-2xl border border-[var(--studio-border)] bg-[var(--studio-surface)] p-2">
        <Table<PricingAiCall>
          className="pricing-table"
          rowKey="key"
          size="small"
          pagination={false}
          dataSource={data.items}
          columns={columns}
        />
      </div>
      <p className="mt-3 flex items-start gap-1.5 text-xs leading-5 text-[var(--studio-text-subtle)]">
        <Info size={12} className="mt-0.5 shrink-0" aria-hidden />
        按 token 计费的功能以典型用量估算展示，实际扣费随输入输出长度浮动；管理端调整价格表后刷新页面即生效。
      </p>
    </section>
  )
}

export default function PricingPage() {
  const pricingQuery = useQuery({
    queryKey: ["pricing"],
    queryFn: () => requestJson<PricingCatalog>("/api/pricing"),
    staleTime: 60_000,
  })
  const catalog = pricingQuery.data
  const [providerKey, setProviderKey] = useState("")
  const [modelKey, setModelKey] = useState("")
  const [resolutionValue, setResolutionValue] = useState("")
  const [duration, setDuration] = useState(5)
  const [referenceCount, setReferenceCount] = useState(0)

  const provider = catalog?.providers.find((item) => item.key === providerKey) ?? catalog?.providers[0]
  const model = provider?.models.find((item) => item.key === modelKey) ?? provider?.models[0]
  const resolution = model?.resolutions.find((item) => item.value === resolutionValue) ?? model?.resolutions[0]
  const bounds = provider && model && resolution
    ? durationBounds(provider.key, model.key, resolution.value)
    : { min: 1, max: 15 }

  useEffect(() => {
    setDuration((current) => Math.min(bounds.max, Math.max(bounds.min, current)))
  }, [bounds.min, bounds.max])

  const policyCards = useMemo(() => {
    if (!catalog) return []
    return [
      { icon: <Coins size={16} />, title: catalog.billing_policy.anchor, description: "积分与人民币的固定锚点，所有云端价都按这一口径换算。" },
      { icon: <RefreshCw size={16} />, title: "提交预扣，失败退回", description: catalog.billing_policy.settlement },
      { icon: <Cpu size={16} />, title: "本地生成免费", description: catalog.billing_policy.local },
    ]
  }, [catalog])

  if (pricingQuery.isLoading) {
    return (
      <div className="flex min-h-[320px] items-center justify-center text-sm text-[var(--studio-text-muted)]">
        <RefreshCw size={16} className="mr-2 animate-spin" aria-hidden /> 正在加载价格…
      </div>
    )
  }
  if (!catalog || !provider || !model || !resolution) {
    return (
      <Alert
        type="warning"
        showIcon
        message="价格数据暂不可用"
        description="价格信息暂时无法加载，请稍后刷新重试。"
      />
    )
  }

  const accent = providerAccent(provider.key)
  return (
    <div className="studio-pricing mx-auto w-full max-w-[1180px]">
      <section className="relative overflow-hidden rounded-[28px] border border-[var(--studio-border)] bg-[var(--studio-surface)] px-6 py-8 sm:px-9">
        <div
          className="pointer-events-none absolute -right-24 -top-24 size-72 rounded-full opacity-60 blur-3xl"
          style={{ background: accent }}
          aria-hidden
        />
        <div className="relative">
          <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--studio-text-muted)]">
            <Tag color="purple" className="!m-0">价格说明</Tag>
            <span>云端视频、生图与 AI 大模型，价格统一按平台积分展示</span>
          </div>
          <h1 className="mt-3 max-w-[760px] text-3xl font-semibold leading-tight tracking-tight text-[var(--studio-text)] sm:text-4xl">
            每一项生成，价格都写清楚
          </h1>
          <p className="mt-3 max-w-[760px] text-sm leading-6 text-[var(--studio-text-secondary)]">
            云端视频按「模型档位 × 分辨率 × 秒数」、生图按张、AI 大模型按次或 token 计费；
            100 积分 = 1 元，提交时预扣，任务失败自动全额退回。
          </p>
          <div className="mt-5 flex flex-wrap gap-2">
            {[
              { icon: <CheckCircle2 size={13} />, text: "提交预扣" },
              { icon: <RefreshCw size={13} />, text: "失败全额退回" },
              { icon: <Clock3 size={13} />, text: "按秒计费" },
              { icon: <Sparkles size={13} />, text: "本地生成免费" },
            ].map((item) => (
              <span
                key={item.text}
                className="inline-flex items-center gap-1.5 rounded-full border border-[var(--studio-border)] bg-[var(--studio-surface-raised)] px-3 py-1 text-xs text-[var(--studio-text-secondary)]"
              >
                {item.icon}
                {item.text}
              </span>
            ))}
          </div>
          <nav className="mt-4 flex flex-wrap gap-2 text-xs" aria-label="价格分类">
            {[
              { href: "#video-pricing", label: "云端视频", icon: <Cpu size={13} aria-hidden /> },
              ...(catalog.image_generation?.models.length
                ? [{ href: "#image-pricing", label: "生图", icon: <Images size={13} aria-hidden /> }]
                : []),
              ...(catalog.ai_calls?.items.length
                ? [{ href: "#ai-pricing", label: "AI 大模型", icon: <Bot size={13} aria-hidden /> }]
                : []),
            ].map((item) => (
              <a
                key={item.href}
                href={item.href}
                className="inline-flex items-center gap-1.5 rounded-full border border-[var(--studio-border)] px-3 py-1 text-[var(--studio-text-secondary)] transition-colors hover:border-[var(--studio-primary)] hover:text-[var(--studio-primary)]"
              >
                {item.icon}
                {item.label}
              </a>
            ))}
          </nav>
        </div>
      </section>

      <section id="video-pricing" className="mt-8 scroll-mt-24">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div>
            <h2 className="text-xl font-semibold text-[var(--studio-text)]">云端视频</h2>
            <p className="mt-1 text-sm leading-6 text-[var(--studio-text-secondary)]">
              按「模型档位 × 分辨率 × 秒数」计费，参考图在免费额度之外按张加收。
            </p>
          </div>
          <Tag color="purple" className="!m-0">GRS（H3 / Agnes 2.5 / Wan 3.0）与 MiniMax 官方</Tag>
        </div>
        <Segmented
          block
          className="mt-4"
          value={provider.key}
          onChange={(value) => {
            setProviderKey(String(value))
            setModelKey("")
            setResolutionValue("")
            setReferenceCount(0)
          }}
          options={catalog.providers.map((item) => ({
            value: item.key,
            label: (
              <span className="inline-flex items-center gap-2">
                <span className="size-2 rounded-full" style={{ background: providerAccent(item.key) }} aria-hidden />
                {item.label}
                <span className="text-xs opacity-70">{item.subtitle}</span>
              </span>
            ),
          }))}
        />
      </section>

      <section className="mt-5 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-xl font-semibold text-[var(--studio-text)]">{provider.label}</h2>
            <Tag color={provider.available ? "green" : "default"} className="!m-0">
              {provider.available ? "已开通" : "暂未开放"}
            </Tag>
            {provider.modes.map((mode) => <Tag key={mode} className="!m-0">{mode}</Tag>)}
          </div>
          <p className="mt-1 max-w-[760px] text-sm leading-6 text-[var(--studio-text-secondary)]">{provider.description}</p>
        </div>
        <Tooltip title="价格随平台调价实时更新。">
          <span className="inline-flex items-center gap-1 text-xs text-[var(--studio-text-muted)]">
            <Info size={13} aria-hidden /> 价格实时同步
          </span>
        </Tooltip>
      </section>

      {!provider.available ? (
        <Alert
          className="mt-4"
          type="warning"
          showIcon
          message="该模型暂未开放"
          description="请选择其他模型，或稍后再试。"
        />
      ) : null}

      <div className="mt-5 grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="grid gap-4">
          <p className="flex items-center gap-1.5 text-xs text-[var(--studio-text-subtle)]">
            <MousePointerClick size={13} aria-hidden />
            点击模型卡片即可切换试算档位
          </p>
          {provider.models.map((item) => (
            <ModelCard
              key={item.key}
              provider={provider}
              model={item}
              selected={item.key === model.key}
              onSelect={() => {
                setModelKey(item.key)
                setResolutionValue("")
              }}
            />
          ))}
          <section className="rounded-2xl border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
            <h3 className="text-sm font-semibold text-[var(--studio-text)]">输入图片费</h3>
            <p className="mt-1 text-xs leading-5 text-[var(--studio-text-muted)]">
              每个任务前 {provider.input_image_free_quota} 张参考图免费，超出部分按模型档位加收：
            </p>
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              {provider.models.map((item) => (
                <div
                  key={item.key}
                  className="flex items-center justify-between gap-3 rounded-xl border border-[var(--studio-border)] bg-[var(--studio-surface-raised)] px-3 py-2 text-xs"
                >
                  <span className="text-[var(--studio-text-secondary)]">{item.label}</span>
                  <span className="tabular-nums font-medium text-[var(--studio-text)]">
                    {item.input_image_credits > 0 ? `${item.input_image_credits} 积分/张` : "暂不额外收费"}
                  </span>
                </div>
              ))}
            </div>
            <ul className="mt-3 grid gap-1.5 text-xs leading-5 text-[var(--studio-text-muted)]">
              {provider.notes.map((note) => <li key={note}>· {note}</li>)}
            </ul>
          </section>
        </div>

        <PricingCalculator
          catalog={catalog}
          provider={provider}
          model={model}
          resolution={resolution}
          duration={duration}
          referenceCount={referenceCount}
          onDurationChange={setDuration}
          onReferenceChange={setReferenceCount}
          onModelChange={(value) => {
            setModelKey(value)
            setResolutionValue("")
          }}
          onResolutionChange={setResolutionValue}
        />
      </div>

      {catalog.image_generation ? (
        <ImagePricingSection data={catalog.image_generation} creditsPerYuan={catalog.credits_per_yuan} />
      ) : null}
      {catalog.ai_calls ? (
        <AiCallPricingSection data={catalog.ai_calls} creditsPerYuan={catalog.credits_per_yuan} />
      ) : null}

      <section className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {policyCards.map((card) => (
          <div key={card.title} className="rounded-2xl border border-[var(--studio-border)] bg-[var(--studio-surface)] p-4">
            <span className="grid size-8 place-items-center rounded-lg bg-[var(--studio-primary-soft)] text-[var(--studio-primary)]">
              {card.icon}
            </span>
            <p className="mt-3 text-sm font-semibold text-[var(--studio-text)]">{card.title}</p>
            <p className="mt-1 text-xs leading-5 text-[var(--studio-text-muted)]">{card.description}</p>
          </div>
        ))}
      </section>

      <p className="mt-6 text-center text-xs leading-5 text-[var(--studio-text-subtle)]">
        价格为平台积分口径，最终以提交时预扣为准；模型分辨率/时长限制以页面与提交校验为准。
      </p>
    </div>
  )
}
