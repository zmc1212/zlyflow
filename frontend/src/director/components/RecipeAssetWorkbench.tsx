import {
  Alert,
  Button,
  Card,
  Collapse,
  Drawer,
  Empty,
  Input,
  Progress,
  Space,
  Tabs,
  Tag,
  Typography,
} from "antd"
import {
  CheckCircle2,
  History,
  ImagePlus,
  Library,
  PanelsTopLeft,
  RefreshCw,
  ScanFace,
  Settings2,
} from "lucide-react"
import { useMemo, useState } from "react"
import MediaPreviewModal from "../../components/MediaPreviewModal"
import {
  emptyRecipeIdentitySpec,
  recipeActiveAssetVersion,
  recipeApprovableAssetVersion,
  recipeApprovedAssetVersion,
  recipeAssetVersionRuntimeStatus,
  type RecipeAssetRendition,
  type RecipeAssetVersion,
  type RecipeCharacter,
  type RecipeLocation,
  type RecipeProp,
} from "../recipe-model"
import { jobProgressFromJob, jobStoredImageUrl } from "../director-submit"
import {
  SIMPLE_ASSET_CARD_STATUS_LABELS,
  simpleAssetCardTone,
} from "../asset-stage-summary"
import RecipeAssetActionRail from "./RecipeAssetActionRail"

export type RecipeAssetTargetKind = "character_portrait" | "character_sheet" | "location" | "prop"

type JobLike = {
  id: string
  status?: string
  progress?: number
  error?: string | null
  outputs?: Array<{ kind?: string; download_url?: string; cloud_url?: string; path?: string }>
}

const VERSION_STATUS_LABELS: Record<string, string> = {
  queued: "排队中",
  running: "生成中",
  succeeded: "可批准",
  failed: "失败",
  interrupted: "已中断",
  cancelled: "已取消",
}

function versionJob(version: RecipeAssetVersion | undefined, jobs: JobLike[]): JobLike | undefined {
  return version?.jobId ? jobs.find((job) => job.id === version.jobId) : undefined
}

function versionStatus(version: RecipeAssetVersion, jobs: JobLike[]): string {
  return recipeAssetVersionRuntimeStatus(version, jobs)
}

function versionImage(version: RecipeAssetVersion | undefined, jobs: JobLike[]): string | undefined {
  if (!version) return undefined
  return version.imageUrl || jobStoredImageUrl(versionJob(version, jobs)) || undefined
}

function renditionPreview(rendition: RecipeAssetRendition, jobs: JobLike[]): {
  version?: RecipeAssetVersion
  imageUrl?: string
  status: string
  progress: number
} {
  const active = recipeActiveAssetVersion(rendition)
  const approved = recipeApprovedAssetVersion(rendition)
  const version = active || approved
  const job = versionJob(version, jobs)
  return {
    version,
    imageUrl: versionImage(version, jobs) || versionImage(approved, jobs),
    status: version ? (job?.status || version.status) : "idle",
    progress: jobProgressFromJob(job, version?.status === "succeeded" ? 100 : 0),
  }
}

function statusTag(label: string, done: boolean, active = false) {
  return (
    <span className={`director-asset-milestone${done ? " is-done" : active ? " is-active" : ""}`}>
      {done ? <CheckCircle2 size={14} /> : <span className="director-asset-milestone-dot" />}
      {label}
    </span>
  )
}

export function AssetVersionHistory({
  rendition,
  approvedVersionId,
  jobs,
  approveLabel,
  onApprove,
}: {
  rendition: RecipeAssetRendition
  approvedVersionId?: string | null
  jobs: JobLike[]
  approveLabel: string
  onApprove: (versionId: string) => void
}) {
  const versions = [...(rendition.versions || [])].reverse()
  if (!versions.length) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有生成候选" />
  return (
    <div className="director-asset-version-list">
      {versions.map((version, index) => {
        const status = versionStatus(version, jobs)
        const imageUrl = versionImage(version, jobs)
        const approved = version.id === approvedVersionId
        const canApprove = status === "succeeded" && Boolean(imageUrl) && !approved
        return (
          <Card key={version.id} size="small" className={`director-asset-version${approved ? " is-approved" : ""}`}>
            <div className="director-asset-version-media">
              {imageUrl ? <img src={imageUrl} alt={`候选 ${versions.length - index}`} /> : (
                <div className="director-asset-version-empty">
                  {status === "queued" || status === "running" ? (
                    <Progress percent={jobProgressFromJob(versionJob(version, jobs), 0)} size="small" showInfo={false} status="active" />
                  ) : "暂无图像"}
                </div>
              )}
            </div>
            <div className="director-asset-version-copy">
              <div className="director-asset-version-title">
                <strong>候选 {versions.length - index}</strong>
                <Tag color={approved ? "success" : status === "failed" ? "error" : status === "running" ? "processing" : "default"}>
                  {approved ? "当前批准" : VERSION_STATUS_LABELS[status] || status}
                </Tag>
              </div>
              <Typography.Paragraph ellipsis={{ rows: 2 }} className="director-asset-version-prompt">
                {version.promptSnapshot || "未保存提示词快照"}
              </Typography.Paragraph>
              {versionJob(version, jobs)?.error ? <Alert type="error" showIcon message={versionJob(version, jobs)?.error} /> : null}
              <Button type={canApprove ? "primary" : "default"} disabled={!canApprove} onClick={() => onApprove(version.id)}>
                {approved ? "已批准" : approveLabel}
              </Button>
            </div>
          </Card>
        )
      })}
    </div>
  )
}

const IDENTITY_FIELDS: Array<{ key: keyof RecipeCharacter["identitySpec"]; label: string; placeholder: string }> = [
  { key: "ageRange", label: "年龄范围", placeholder: "例：20–25 岁" },
  { key: "regionalAppearance", label: "地域外观", placeholder: "例：东亚面孔" },
  { key: "faceFeatures", label: "面部结构", placeholder: "脸型、眉眼、鼻唇等可辨识结构" },
  { key: "hair", label: "头发", placeholder: "发色、长度、发型与发际线" },
  { key: "skinTone", label: "肤色", placeholder: "稳定、客观的肤色描述" },
  { key: "bodyBuild", label: "体型", placeholder: "身高感、肩宽与体态比例" },
  { key: "distinguishingMarks", label: "辨识标记", placeholder: "痣、疤、纹身等；没有可留空" },
  { key: "immutableAccessories", label: "固定配饰", placeholder: "每个镜头都应保留的配饰" },
  { key: "avoidChanges", label: "禁止漂移", placeholder: "明确不得改变的脸、头发或身体特征" },
]

export function CharacterAssetCard({
  character,
  jobs,
  onChange,
  onGenerate,
  onApprove,
  onSaveToLibrary,
}: {
  character: RecipeCharacter
  jobs: JobLike[]
  onChange: (patch: Partial<RecipeCharacter>) => void
  onGenerate: (kind: "character_portrait" | "character_sheet", lookId?: string) => void
  onApprove: (kind: "character_portrait" | "character_sheet", versionId: string, lookId?: string) => void
  onSaveToLibrary: () => void
}) {
  const [detailsOpen, setDetailsOpen] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [previewOpen, setPreviewOpen] = useState(false)
  const look = character.looks?.[0]
  const portrait = character.portrait || { versions: [] }
  const identitySpec = { ...emptyRecipeIdentitySpec(), ...(character.identitySpec || {}) }
  const portraitApproved = recipeApprovedAssetVersion(portrait)
  const sheetApproved = recipeApprovedAssetVersion(look?.sheet)
  const portraitState = renditionPreview(portrait, jobs)
  const sheetState = look ? renditionPreview(look.sheet, jobs) : { status: "idle", progress: 0 }
  const shown = sheetApproved
    ? versionImage(sheetApproved, jobs)
    : sheetState.imageUrl || versionImage(portraitApproved, jobs) || portraitState.imageUrl
  const activeState = sheetState.status !== "idle" ? sheetState : portraitState
  const generating = activeState.status === "queued" || activeState.status === "running"
  const nextKind = portraitApproved ? "character_sheet" : "character_portrait"
  const portraitApprovable = recipeApprovableAssetVersion(portrait, jobs)
  const sheetApprovable = look ? recipeApprovableAssetVersion(look.sheet, jobs) : undefined
  const approvable = sheetApprovable || portraitApprovable
  const approveKind: "character_portrait" | "character_sheet" | null = sheetApprovable
    ? "character_sheet"
    : portraitApprovable
      ? "character_portrait"
      : null
  const cardTone = sheetApproved
    ? "ready"
    : generating
      ? "running"
      : approvable
        ? "pending"
        : portraitApproved
          ? "idle"
          : "idle"
  const statusLabel = SIMPLE_ASSET_CARD_STATUS_LABELS[cardTone as keyof typeof SIMPLE_ASSET_CARD_STATUS_LABELS] || "待生成"
  const totalVersions = portrait.versions.length + (look?.sheet.versions.length || 0)
  const assumptions = character.aiAssumptions || []
  const generateHint = portraitApproved
    ? sheetApproved ? "生成新的四视角定妆板候选" : "生成四视角定妆板"
    : "生成身份肖像"

  const historyItems = useMemo(() => [
    {
      key: "portrait",
      label: `身份肖像 ${portrait.versions.length}`,
      children: (
        <AssetVersionHistory
          rendition={portrait}
          approvedVersionId={portrait.approvedVersionId}
          jobs={jobs}
          approveLabel="批准为身份锚点"
          onApprove={(versionId) => onApprove("character_portrait", versionId)}
        />
      ),
    },
    {
      key: "sheet",
      label: `定妆板 ${look?.sheet.versions.length || 0}`,
      children: look ? (
        <AssetVersionHistory
          rendition={look.sheet || { versions: [] }}
          approvedVersionId={look.sheet?.approvedVersionId}
          jobs={jobs}
          approveLabel="批准这版定妆"
          onApprove={(versionId) => onApprove("character_sheet", versionId, look.id)}
        />
      ) : <Empty description="还没有角色造型" />,
    },
  ], [portrait, jobs, look, onApprove])

  return (
    <Card className="director-asset-card director-character-card" size="small">
      <button
        type="button"
        className={`director-character-visual${shown ? " has-image" : ""}`}
        onClick={() => shown && setPreviewOpen(true)}
        disabled={!shown}
      >
        {shown ? <img src={shown} alt={character.name} /> : (
          <div className="director-character-empty">
            {generating ? (
              <>
                <Progress percent={activeState.progress} size="small" status="active" showInfo={false} />
                <span>{VERSION_STATUS_LABELS[activeState.status] || "生成中"}</span>
              </>
            ) : (
              <>
                <ScanFace size={26} />
                <strong>从身份肖像开始</strong>
                <span>先锁定脸，再生成多视角定妆板</span>
              </>
            )}
          </div>
        )}
        {sheetApproved ? <span className="director-asset-status-chip is-ready">已批准</span> : (
          <span className={`director-asset-status-chip is-${cardTone}`}>{statusLabel}</span>
        )}
      </button>
      <div className="director-character-body">
        <div className="director-character-heading">
          <Input value={character.name} aria-label="角色名称" onChange={(event) => onChange({ name: event.target.value })} />
          {character.role ? <span>{character.role}</span> : null}
        </div>
        <Typography.Paragraph ellipsis={{ rows: 2 }}>{character.description}</Typography.Paragraph>
        <div className="director-asset-milestones" aria-label="定妆进度">
          {statusTag("规格", character.specStatus === "approved" || Boolean(portraitApproved), !portraitApproved)}
          {statusTag("肖像", Boolean(portraitApproved), !portraitApproved && generating)}
          {statusTag("定妆板", Boolean(sheetApproved), Boolean(portraitApproved) && !sheetApproved)}
        </div>
        <RecipeAssetActionRail
          items={[
            {
              key: "approve",
              label: "批准",
              icon: <CheckCircle2 size={14} />,
              emphasis: approvable ? "primary" : "default",
              disabled: !approvable || !approveKind,
              hint: sheetApprovable
                ? "批准这版四视角定妆板"
                : portraitApprovable
                  ? "批准为身份锚点"
                  : sheetApproved
                    ? "定妆板已批准"
                    : "请先生成可批准候选",
              onClick: () => {
                if (!approvable || !approveKind) return
                onApprove(
                  approveKind,
                  approvable.id,
                  approveKind === "character_sheet" ? look?.id : undefined,
                )
              },
            },
            {
              key: "generate",
              label: portraitApproved ? (sheetApproved ? "重生成" : "定妆板") : "肖像",
              icon: portraitApproved ? <PanelsTopLeft size={14} /> : <ScanFace size={14} />,
              emphasis: !approvable && !sheetApproved ? "primary" : "default",
              loading: generating,
              hint: generateHint,
              onClick: () => onGenerate(nextKind, look?.id),
            },
            {
              key: "history",
              label: totalVersions ? `候选 ${totalVersions}` : "候选",
              icon: <History size={14} />,
              disabled: !totalVersions,
              hint: "查看肖像与定妆板候选",
              onClick: () => setHistoryOpen(true),
            },
            {
              key: "library",
              label: "入库",
              icon: <Library size={14} />,
              disabled: !sheetApproved,
              hint: sheetApproved ? "将已批准定妆存入资产库" : "批准定妆板后可入库",
              onClick: onSaveToLibrary,
            },
          ]}
        />
        <Button icon={<Settings2 size={14} />} onClick={() => setDetailsOpen(true)} className="director-asset-spec-link">
          编辑角色设定
        </Button>
      </div>

      <Drawer className="director-asset-drawer" title={`${character.name} · 角色规格`} open={detailsOpen} onClose={() => setDetailsOpen(false)} width={560}>
        <div className="director-character-spec-form">
          <label><span>角色定位</span><Input value={character.role} onChange={(event) => onChange({ role: event.target.value })} /></label>
          <label><span>用户可读描述</span><Input.TextArea value={character.description} autoSize={{ minRows: 3, maxRows: 6 }} onChange={(event) => onChange({ description: event.target.value })} /></label>
          <Typography.Title level={5}>不可变身份特征</Typography.Title>
          <div className="director-character-identity-grid">
            {IDENTITY_FIELDS.map((field) => (
              <label key={field.key}>
                <span>{field.label}</span>
                <Input.TextArea
                  value={identitySpec[field.key]}
                  placeholder={field.placeholder}
                  autoSize={{ minRows: 2, maxRows: 4 }}
                  onChange={(event) => onChange({
                    identitySpec: { ...identitySpec, [field.key]: event.target.value },
                  })}
                />
              </label>
            ))}
          </div>
          {assumptions.length ? (
            <Alert
              type="warning"
              showIcon
              message="AI 补全了以下未明确设定"
              description={assumptions.join("；")}
            />
          ) : null}
          {look ? (
            <Collapse items={[{
              key: look.id,
              label: `造型 · ${look.name}`,
              children: (
                <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                  <Input value={look.name} onChange={(event) => onChange({
                    looks: (character.looks || []).map((item) => item.id === look.id ? { ...item, name: event.target.value } : item),
                  })} />
                  <Input.TextArea value={look.appearanceDetails} autoSize={{ minRows: 4, maxRows: 8 }} onChange={(event) => onChange({
                    looks: (character.looks || []).map((item) => item.id === look.id ? { ...item, appearanceDetails: event.target.value } : item),
                  })} />
                </Space>
              ),
            }]} />
          ) : null}
        </div>
      </Drawer>
      <Drawer className="director-asset-drawer" title={`${character.name} · 候选历史`} open={historyOpen} onClose={() => setHistoryOpen(false)} width={680}>
        <Tabs items={historyItems} />
      </Drawer>
      {shown ? (
        <MediaPreviewModal open={previewOpen} kind="image" src={shown} title={character.name} description={character.description} onClose={() => setPreviewOpen(false)} />
      ) : null}
    </Card>
  )
}

type SimpleAsset = RecipeLocation | RecipeProp

export function SimpleRenditionAssetCard({
  asset,
  kind,
  jobs,
  onChange,
  onGenerate,
  onApprove,
  onSaveToLibrary,
}: {
  asset: SimpleAsset
  kind: "location" | "prop"
  jobs: JobLike[]
  onChange: (patch: Partial<SimpleAsset>) => void
  onGenerate: () => void
  onApprove: (versionId: string) => void
  onSaveToLibrary: () => void
}) {
  const [historyOpen, setHistoryOpen] = useState(false)
  const [previewOpen, setPreviewOpen] = useState(false)
  const rendition = ("plate" in asset ? asset.plate : asset.turnaround) || { versions: [] }
  const approved = recipeApprovedAssetVersion(rendition)
  const approvable = recipeApprovableAssetVersion(rendition, jobs)
  const state = renditionPreview(rendition, jobs)
  const imageUrl = versionImage(approved, jobs) || state.imageUrl
  const generating = state.status === "queued" || state.status === "running"
  const noun = kind === "location" ? "场景母版" : "道具转面"
  const hasPreview = Boolean(imageUrl)
  const generateLabel = approved
    ? "重新生成"
    : hasPreview
      ? "重新生成"
      : "生成"
  const cardTone = simpleAssetCardTone(Boolean(approved), Boolean(approvable), generating, state.status)
  const statusLabel = SIMPLE_ASSET_CARD_STATUS_LABELS[cardTone]
  const versionCount = rendition.versions.length
  return (
    <Card className="director-asset-card director-simple-asset-card" size="small">
      <button type="button" className="director-simple-asset-visual" onClick={() => imageUrl && setPreviewOpen(true)} disabled={!imageUrl}>
        {imageUrl ? <img src={imageUrl} alt={asset.name} /> : generating ? (
          <div><Progress percent={state.progress} size="small" showInfo={false} status="active" /><span>{VERSION_STATUS_LABELS[state.status]}</span></div>
        ) : (
          <div><ImagePlus size={24} /><span>待生成{noun}</span></div>
        )}
        <span className={`director-asset-status-chip is-${cardTone}`}>{statusLabel}</span>
      </button>
      <div className="director-simple-asset-meta">
        <Input value={asset.name} aria-label={`${noun}名称`} onChange={(event) => onChange({ name: event.target.value })} />
        <Typography.Text type="secondary" className="director-simple-asset-subline">
          {versionCount ? `候选 ${versionCount}` : "尚无候选"} · {statusLabel}
        </Typography.Text>
      </div>
      <Input.TextArea
        value={asset.description}
        autoSize={{ minRows: 1, maxRows: 3 }}
        placeholder="场景描述"
        onChange={(event) => onChange({ description: event.target.value })}
      />
      <RecipeAssetActionRail
        items={[
          {
            key: "approve",
            label: "批准",
            icon: <CheckCircle2 size={14} />,
            emphasis: approvable ? "primary" : "default",
            disabled: !approvable,
            hint: approvable ? `批准当前${noun}候选` : approved ? "已批准当前版本" : "请先生成成功候选",
            onClick: () => approvable && onApprove(approvable.id),
          },
          {
            key: "generate",
            label: generateLabel,
            icon: <RefreshCw size={14} />,
            emphasis: !approvable && !approved ? "primary" : "default",
            loading: generating,
            hint: approved ? `生成新的${noun}候选` : hasPreview ? `重新生成${noun}` : `生成${noun}`,
            onClick: onGenerate,
          },
          {
            key: "history",
            label: versionCount ? `候选 ${versionCount}` : "候选",
            icon: <History size={14} />,
            disabled: !versionCount,
            hint: versionCount ? "查看并切换历史候选" : "还没有候选版本",
            onClick: () => setHistoryOpen(true),
          },
          {
            key: "library",
            label: "入库",
            icon: <Library size={14} />,
            disabled: !approved,
            hint: approved ? "将已批准版本存入资产库" : "批准后才能存入资产库",
            onClick: onSaveToLibrary,
          },
        ]}
      />
      <Drawer className="director-asset-drawer" title={`${asset.name} · 候选历史`} open={historyOpen} onClose={() => setHistoryOpen(false)} width={680}>
        <AssetVersionHistory rendition={rendition} approvedVersionId={rendition.approvedVersionId} jobs={jobs} approveLabel={`批准这版${noun}`} onApprove={onApprove} />
      </Drawer>
      {imageUrl ? <MediaPreviewModal open={previewOpen} kind="image" src={imageUrl} title={asset.name} description={asset.description} onClose={() => setPreviewOpen(false)} /> : null}
    </Card>
  )
}
