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
  recipeApprovedAssetVersion,
  type RecipeAssetRendition,
  type RecipeAssetVersion,
  type RecipeCharacter,
  type RecipeLocation,
  type RecipeProp,
} from "../recipe-model"
import { jobProgressFromJob, jobStoredImageUrl } from "../director-submit"

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
  return versionJob(version, jobs)?.status || version.status
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

function AssetVersionHistory({
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
  const nextLabel = portraitApproved
    ? sheetApproved ? "生成新定妆候选" : "生成四视角定妆板"
    : "生成身份肖像"
  const totalVersions = portrait.versions.length + (look?.sheet.versions.length || 0)
  const assumptions = character.aiAssumptions || []

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
        {sheetApproved ? <span className="director-character-approved"><CheckCircle2 size={14} /> 已批准</span> : null}
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
        <div className="director-asset-card-actions">
          <Button
            type="primary"
            icon={portraitApproved ? <PanelsTopLeft size={14} /> : <ScanFace size={14} />}
            loading={generating}
            onClick={() => onGenerate(nextKind, look?.id)}
          >
            {nextLabel}
          </Button>
          <Button icon={<Settings2 size={14} />} onClick={() => setDetailsOpen(true)}>设定</Button>
          <Button icon={<History size={14} />} onClick={() => setHistoryOpen(true)}>候选 {totalVersions}</Button>
        </div>
        <Button
          type="text"
          icon={<Library size={14} />}
          disabled={!sheetApproved}
          onClick={onSaveToLibrary}
          className="director-asset-save"
        >
          {sheetApproved ? "将已批准定妆存入资产库" : "批准定妆后可存入资产库"}
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
  const state = renditionPreview(rendition, jobs)
  const imageUrl = versionImage(approved, jobs) || state.imageUrl
  const generating = state.status === "queued" || state.status === "running"
  const noun = kind === "location" ? "场景母版" : "道具转面"
  return (
    <Card className="director-asset-card director-simple-asset-card" size="small">
      <button type="button" className="director-simple-asset-visual" onClick={() => imageUrl && setPreviewOpen(true)} disabled={!imageUrl}>
        {imageUrl ? <img src={imageUrl} alt={asset.name} /> : generating ? (
          <div><Progress percent={state.progress} size="small" showInfo={false} status="active" /><span>{VERSION_STATUS_LABELS[state.status]}</span></div>
        ) : (
          <div><ImagePlus size={24} /><span>待生成{noun}</span></div>
        )}
        {approved ? <span className="director-character-approved"><CheckCircle2 size={14} /> 已批准</span> : null}
      </button>
      <Input value={asset.name} aria-label={`${noun}名称`} onChange={(event) => onChange({ name: event.target.value })} />
      <Input.TextArea value={asset.description} autoSize={{ minRows: 2, maxRows: 4 }} onChange={(event) => onChange({ description: event.target.value })} />
      <div className="director-asset-card-actions">
        <Button type="primary" icon={<RefreshCw size={14} />} loading={generating} onClick={onGenerate}>
          {approved ? `生成新${noun}候选` : `生成${noun}`}
        </Button>
        <Button icon={<History size={14} />} onClick={() => setHistoryOpen(true)}>候选 {rendition.versions.length}</Button>
      </div>
      <Button type="text" icon={<Library size={14} />} disabled={!approved} onClick={onSaveToLibrary} className="director-asset-save">
        {approved ? "将已批准版本存入资产库" : "批准后可存入资产库"}
      </Button>
      <Drawer className="director-asset-drawer" title={`${asset.name} · 候选历史`} open={historyOpen} onClose={() => setHistoryOpen(false)} width={680}>
        <AssetVersionHistory rendition={rendition} approvedVersionId={rendition.approvedVersionId} jobs={jobs} approveLabel={`批准这版${noun}`} onApprove={onApprove} />
      </Drawer>
      {imageUrl ? <MediaPreviewModal open={previewOpen} kind="image" src={imageUrl} title={asset.name} description={asset.description} onClose={() => setPreviewOpen(false)} /> : null}
    </Card>
  )
}
