import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Alert, Button, Input, Modal, Select, Switch, Table, Tag, message } from "antd"
import { CheckCircle2, Cloud, CloudDownload, GripVertical, KeyRound, Plus, RefreshCw, WalletCards } from "lucide-react"
import { useEffect, useMemo, useState, useRef } from "react"
import { jsonMutation, requestJson } from "../api"
import { reorderCatalogRows } from "./grs-catalog-order"

type ProviderConfig = {
  enabled: boolean
  base_url: string
  api_key_masked?: string | null
  has_api_key: boolean
  credential_ready: boolean
  last_test_status?: string | null
  last_test_message?: string | null
  last_test_at?: string | null
  last_balance?: number | null
  last_balance_at?: string | null
  available: boolean
  unavailable_reason?: string | null
}

type CatalogModel = {
  workflow_id: string
  provider_model: string
  display_name: string
  description: string
  profile: string
  resolutions: string[] | null
  enabled: boolean
  sort_order: number
  is_default: boolean
  builtin: boolean
  credit_cost?: number | null
}

type CatalogPayload = {
  models: CatalogModel[]
  profiles: { value: string; label: string }[]
}

type PlatformModel = {
  provider_model: string
  workflow_id: string
  display_name: string
  profile: string
  resolutions: string[] | null
  profile_source: "builtin" | "guess"
  in_catalog: boolean
  enabled: boolean
  is_default: boolean
  description?: string
  credit_cost?: number | null
}

type PlatformPayload = {
  models: PlatformModel[]
  off_platform: { provider_model: string; workflow_id: string; display_name: string; enabled: boolean }[]
  total: number
  fetched_at: string
  message?: string | null
}

type ImportPayload = CatalogPayload & { created: string[]; skipped: string[] }

type PlatformDraft = { display_name: string; profile: string; enabled: boolean }

export default function GrsProviderSettings({ csrfToken }: { csrfToken: string }) {
  const queryClient = useQueryClient()
  const query = useQuery({ queryKey: ["grs-provider"], queryFn: () => requestJson<ProviderConfig>("/api/admin/providers/grs") })
  const catalogQuery = useQuery({
    queryKey: ["grs-image-models"],
    queryFn: () => requestJson<CatalogPayload>("/api/admin/providers/grs/models"),
  })
  const [enabled, setEnabled] = useState(false)
  const [baseUrl, setBaseUrl] = useState("https://grsai.dakka.com.cn")
  const [apiKey, setApiKey] = useState("")
  const [models, setModels] = useState<CatalogModel[]>([])
  const [addOpen, setAddOpen] = useState(false)
  const [newModelId, setNewModelId] = useState("")
  const [newDisplayName, setNewDisplayName] = useState("")
  const [newProfile, setNewProfile] = useState("nano_banana")
  const [platformOpen, setPlatformOpen] = useState(false)
  const [platform, setPlatform] = useState<PlatformModel[]>([])
  const [platformTotal, setPlatformTotal] = useState(0)
  const [offPlatform, setOffPlatform] = useState<string[]>([])
  const [platformNotice, setPlatformNotice] = useState<string | null>(null)
  const [drafts, setDrafts] = useState<Record<string, PlatformDraft>>({})
  const [selected, setSelected] = useState<string[]>([])
  const formLoaded = useRef(false)

  const applyConfig = (config: ProviderConfig) => {
    formLoaded.current = true
    setEnabled(config.enabled)
    setBaseUrl(config.base_url)
    queryClient.setQueryData(["grs-provider"], config)
  }

  useEffect(() => {
    if (!query.data || formLoaded.current) return
    applyConfig(query.data)
  }, [query.data])

  useEffect(() => {
    if (catalogQuery.data) setModels(catalogQuery.data.models)
  }, [catalogQuery.data])

  const profileLabel = useMemo(() => {
    const mapping = new Map((catalogQuery.data?.profiles ?? []).map((item) => [item.value, item.label]))
    return (profile: string) => mapping.get(profile) || profile
  }, [catalogQuery.data])

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["grs-provider"] })
    queryClient.invalidateQueries({ queryKey: ["grs-image-models"] })
  }
  const save = useMutation({
    mutationFn: () => requestJson<ProviderConfig>("/api/admin/providers/grs", jsonMutation(csrfToken, {
      enabled, base_url: baseUrl, api_key: apiKey || null,
    }, "PUT")),
    onSuccess: (config) => {
      setApiKey("")
      applyConfig(config)
      refresh()
      message.success("GRS 图片供应商配置已保存")
    },
  })
  const saveModels = useMutation({
    mutationFn: (next: CatalogModel[]) => requestJson<CatalogPayload>("/api/admin/providers/grs/models", jsonMutation(csrfToken, {
      models: next.map((item) => ({
        workflow_id: item.workflow_id,
        display_name: item.display_name,
        enabled: item.enabled,
        sort_order: item.sort_order,
        is_default: item.is_default,
      })),
    }, "PUT")),
    onSuccess: (payload) => {
      setModels(payload.models)
      queryClient.invalidateQueries({ queryKey: ["grs-image-models"] })
      message.success("生图模型目录已保存")
    },
  })
  const addModel = useMutation({
    mutationFn: () => requestJson<CatalogPayload>("/api/admin/providers/grs/models", jsonMutation(csrfToken, {
      provider_model: newModelId.trim(),
      display_name: newDisplayName.trim() || newModelId.trim(),
      profile: newProfile,
      enabled: true,
    })),
    onSuccess: (payload) => {
      setModels(payload.models)
      setAddOpen(false)
      setNewModelId("")
      setNewDisplayName("")
      queryClient.invalidateQueries({ queryKey: ["grs-image-models"] })
      message.success("已添加生图模型")
    },
  })
  const syncCatalog = useMutation({
    mutationFn: () => requestJson<CatalogPayload>("/api/admin/providers/grs/models/sync", {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken },
    }),
    onSuccess: (payload) => {
      setModels(payload.models)
      queryClient.invalidateQueries({ queryKey: ["grs-image-models"] })
      message.success("已同步内置目录中缺失的模型")
    },
  })
  const fetchPlatform = useMutation({
    mutationFn: () => requestJson<PlatformPayload>("/api/admin/providers/grs/models/fetch", jsonMutation(csrfToken, {
      base_url: baseUrl,
      api_key: apiKey || null,
    })),
    onSuccess: (payload) => {
      const nextDrafts: Record<string, PlatformDraft> = {}
      payload.models.forEach((item) => {
        if (item.in_catalog) return
        nextDrafts[item.provider_model] = { display_name: item.display_name, profile: item.profile, enabled: true }
      })
      setPlatform(payload.models)
      setPlatformTotal(payload.total)
      setOffPlatform(payload.off_platform.map((item) => item.provider_model))
      setDrafts(nextDrafts)
      setSelected(Object.keys(nextDrafts))
      setPlatformNotice(payload.message ?? null)
      setPlatformOpen(true)
      if (!payload.message) {
        message.success(`平台在售生图模型 ${payload.models.length} 个（上游共 ${payload.total} 个）`)
      }
    },
  })
  const importModels = useMutation({
    mutationFn: () => requestJson<ImportPayload>("/api/admin/providers/grs/models/import", jsonMutation(csrfToken, {
      models: selected.map((providerModel) => ({
        provider_model: providerModel,
        display_name: drafts[providerModel]?.display_name,
        profile: drafts[providerModel]?.profile,
        enabled: drafts[providerModel]?.enabled ?? true,
      })),
    })),
    onSuccess: (payload) => {
      setModels(payload.models)
      setPlatform((current) => current.map((item) => ({ ...item, in_catalog: true })))
      setOffPlatform((current) => current.filter((item) => !selected.includes(item)))
      setPlatformOpen(false)
      queryClient.invalidateQueries({ queryKey: ["grs-image-models"] })
      const skipped = payload.skipped.length ? `，跳过 ${payload.skipped.length} 个已在目录中的模型` : ""
      message.success(`已导入 ${payload.created.length} 个平台生图模型${skipped}`)
    },
  })
  const test = useMutation({
    mutationFn: () => requestJson<ProviderConfig>("/api/admin/providers/grs/test", jsonMutation(csrfToken, {
      base_url: baseUrl,
      api_key: apiKey || null,
    })),    onSuccess: () => {
      refresh()
      message.success("GRS 连接测试成功")
    },
  })
  const balance = useMutation({
    mutationFn: () => requestJson<{ credits: number }>("/api/admin/providers/grs/balance", { method: "POST", headers: { "X-CSRF-Token": csrfToken } }),
    onSuccess: () => {
      refresh()
      message.success("上游余额查询成功")
    },
  })
  const error = save.error ?? saveModels.error ?? addModel.error ?? syncCatalog.error ?? fetchPlatform.error
    ?? importModels.error ?? test.error ?? balance.error ?? query.error ?? catalogQuery.error

  const updateModel = (workflowId: string, patch: Partial<CatalogModel>) => {
    setModels((current) => current.map((item) => {
      if (item.workflow_id !== workflowId) {
        return patch.is_default ? { ...item, is_default: false } : item
      }
      return { ...item, ...patch }
    }))
  }

  const updateDraft = (providerModel: string, patch: Partial<PlatformDraft>) => {
    setDrafts((current) => ({ ...current, [providerModel]: { ...current[providerModel], ...patch } }))
  }

  // 拖拽排序：手柄本身可拖，行只作为放置目标，行内输入框因此不受影响。
  const [draggingRow, setDraggingRow] = useState<string | null>(null)
  const [dropTargetRow, setDropTargetRow] = useState<string | null>(null)

  const endRowDrag = () => {
    setDraggingRow(null)
    setDropTargetRow(null)
  }

  const reorderModels = (fromId: string, toId: string) => {
    setModels((current) => reorderCatalogRows(current, fromId, toId))
  }

  const serverModels = catalogQuery.data?.models ?? []
  const catalogDirty = models.length !== serverModels.length || models.some((item, index) => {
    const saved = serverModels[index]
    return !saved
      || saved.workflow_id !== item.workflow_id
      || saved.display_name !== item.display_name
      || saved.enabled !== item.enabled
      || saved.is_default !== item.is_default
      || saved.sort_order !== item.sort_order
  })

  return (
    <main className="mx-auto max-w-[1020px] px-5 py-6 lg:px-8">
      <div className="flex items-start gap-4 border-b border-black/[0.06] pb-5">
        <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-[#7047f6]/10 text-[#7047f6]">
          <Cloud size={22} />
        </span>
        <div>
          <h2 className="text-base font-semibold text-[#111827]">GRS 图片供应商</h2>
          <p className="mt-1 text-xs leading-5 text-[#4b5563]">
            单一主配置负责连接与余额；启用的模型会作为独立工作流出现在创作页。
          </p>
        </div>
      </div>

      {!query.data?.credential_ready ? (
        <Alert
          className="mt-5"
          type="warning"
          showIcon
          message="凭证主密钥不可用"
          description="请在部署环境设置 ZLY_AI_VIDEO_STUDIO_CREDENTIAL_KEY。视频功能不受影响，图片提交会保持锁定。"
        />
      ) : null}

      <section className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="rounded-2xl border border-black/[0.06] bg-white p-6 shadow-sm space-y-5">
          <div className="flex items-center justify-between gap-4 border-b border-black/[0.06] pb-4">
            <div>
              <p className="text-sm font-medium text-[#111827]">启用 GRS 生图</p>
              <p className="mt-0.5 text-xs text-[#6b7280]">关闭后仍保留图片入口和历史，只锁定提交。</p>
            </div>
            <Switch checked={enabled} onChange={setEnabled} />
          </div>

          <div>
            <label className="block text-xs font-medium text-[#4b5563]">Base URL</label>
            <Input
              className="mt-1.5"
              value={baseUrl}
              onChange={(event) => setBaseUrl(event.target.value)}
              placeholder="https://grsai.dakka.com.cn"
            />
            <p className="mt-1.5 text-xs leading-5 text-[#6b7280]">
              国内节点 <code>https://grsai.dakka.com.cn</code>，国际节点 <code>https://grsaiapi.com</code>。
              国内节点连不上时改用国际节点，先点「测试连接」再保存。
            </p>
          </div>

          <div>
            <label className="block text-xs font-medium text-[#4b5563]">API Key</label>
            <Input.Password
              className="mt-1.5"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              prefix={<KeyRound size={15} className="text-[#9ca3af]" />}
              placeholder={query.data?.api_key_masked || "输入新的 API Key"}
            />
          </div>

          {error ? <Alert type="error" showIcon message={error.message} /> : null}

          <div className="flex flex-wrap gap-3 pt-2">
            <Button type="primary" loading={save.isPending} onClick={() => save.mutate()}>
              保存配置
            </Button>
            <Button loading={test.isPending} onClick={() => test.mutate()} icon={<CheckCircle2 size={15} />}>
              测试连接
            </Button>
            <Button loading={balance.isPending} onClick={() => balance.mutate()} icon={<WalletCards size={15} />}>
              查询余额
            </Button>
          </div>
        </div>

        <aside className="rounded-2xl border border-black/[0.06] bg-white p-6 shadow-sm">
          <p className="text-xs font-semibold uppercase tracking-wider text-[#6b7280]">当前状态</p>
          <p className={`mt-3 text-sm font-semibold ${query.data?.available ? "text-emerald-600" : "text-amber-600"}`}>
            {query.data?.available ? "● 可以提交图片任务" : "● 图片提交已锁定"}
          </p>
          {query.data?.unavailable_reason ? (
            <p className="mt-2 text-xs leading-5 text-[#6b7280]">{query.data.unavailable_reason}</p>
          ) : null}

          <dl className="mt-6 space-y-4 text-xs">
            <div>
              <dt className="text-[#6b7280]">最近测试</dt>
              <dd className="mt-1 font-medium text-[#111827]">
                {query.data?.last_test_status
                  ? `${query.data.last_test_status} · ${query.data.last_test_at ? new Date(query.data.last_test_at).toLocaleString("zh-CN", { hour12: false }) : ""}`
                  : "尚未测试"}
              </dd>
            </div>
            <div>
              <dt className="text-[#6b7280]">上游余额</dt>
              <dd className="mt-1 font-mono font-medium text-[#111827]">
                {query.data?.last_balance !== undefined && query.data?.last_balance !== null
                  ? `${query.data.last_balance} 点`
                  : "尚未查询"}
              </dd>
            </div>
            <div>
              <dt className="text-[#6b7280]">已启用模型</dt>
              <dd className="mt-1 font-medium text-[#111827]">{models.filter((item) => item.enabled).length} 个</dd>
            </div>
          </dl>
        </aside>
      </section>

      <section className="mt-6 rounded-2xl border border-black/[0.06] bg-white p-6 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-[#111827]">
              生图模型目录
              {catalogDirty ? <Tag className="ml-2 align-middle" color="purple">有未保存的改动</Tag> : null}
            </h3>
            <p className="mt-1 text-xs leading-5 text-[#6b7280]">
              勾选启用后会出现在创作页「选择工作流」。点「从平台拉取模型」读取 GRS 上游在售清单，
              新模型直接勾选导入，不必再手填模型 ID。
            </p>
            <p className="mt-1 text-xs leading-5 text-[#6b7280]">
              拖动行首的手柄可以调整创作页里模型的显示顺序，排在前面的先显示；「默认」开关独立于顺序，
              只决定创作页预选和导演台自动出图使用的模型。调整完点「保存目录」才会生效。
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button type="primary" icon={<CloudDownload size={14} />} loading={fetchPlatform.isPending} onClick={() => fetchPlatform.mutate()}>
              从平台拉取模型
            </Button>
            <Button type={catalogDirty ? "primary" : "default"} loading={saveModels.isPending} onClick={() => saveModels.mutate(models)}>
              保存目录
            </Button>
            <Button icon={<Plus size={14} />} onClick={() => setAddOpen(true)}>手动添加</Button>
            <Button icon={<RefreshCw size={14} />} loading={syncCatalog.isPending} onClick={() => syncCatalog.mutate()}>
              补充内置目录
            </Button>
          </div>
        </div>

        {offPlatform.length ? (
          <Alert
            className="mt-4"
            type="info"
            showIcon
            message={`本次平台清单里没有 ${offPlatform.length} 个目录模型`}
            description={`${offPlatform.join("、")} 已不在上游 /v1/models 返回中，可能已下架或改名。停用后创作页不再出现该模型。`}
          />
        ) : null}

        <Table
          className="mt-4"
          rowKey="workflow_id"
          size="middle"
          pagination={false}
          dataSource={models}
          onRow={(record) => ({
            onDragOver: (event) => {
              if (!draggingRow || draggingRow === record.workflow_id) return
              event.preventDefault()
              event.dataTransfer.dropEffect = "move"
              if (dropTargetRow !== record.workflow_id) setDropTargetRow(record.workflow_id)
            },
            onDragLeave: () => {
              if (dropTargetRow === record.workflow_id) setDropTargetRow(null)
            },
            onDrop: (event) => {
              event.preventDefault()
              if (draggingRow && draggingRow !== record.workflow_id) reorderModels(draggingRow, record.workflow_id)
              endRowDrag()
            },
            style: {
              opacity: draggingRow === record.workflow_id ? 0.45 : undefined,
              backgroundColor: dropTargetRow === record.workflow_id ? "rgba(112, 71, 246, 0.12)" : undefined,
            },
          })}
          columns={[
            {
              key: "drag",
              width: 38,
              render: (_, record) => (
                <span
                  title="拖动调整创作页显示顺序"
                  draggable
                  onDragStart={(event) => {
                    setDraggingRow(record.workflow_id)
                    event.dataTransfer.effectAllowed = "move"
                    event.dataTransfer.setData("text/plain", record.workflow_id)
                  }}
                  onDragEnd={endRowDrag}
                  className="grid h-6 w-6 cursor-grab place-items-center rounded-md text-[#9ca3af] hover:bg-[#7047f6]/10 active:cursor-grabbing hover:text-[#7047f6]"
                >
                  <GripVertical size={15} />
                </span>
              ),
            },
            {
              title: "启用",
              dataIndex: "enabled",
              width: 72,
              render: (_, record) => (
                <Switch checked={record.enabled} onChange={(checked) => updateModel(record.workflow_id, { enabled: checked })} />
              ),
            },
            {
              title: "显示名",
              dataIndex: "display_name",
              render: (_, record) => (
                <Input
                  value={record.display_name}
                  onChange={(event) => updateModel(record.workflow_id, { display_name: event.target.value })}
                />
              ),
            },
            {
              title: "上游模型 ID",
              dataIndex: "provider_model",
              render: (value: string, record) => (
                <span className="font-mono text-xs text-[#1f2937]">
                  {value}
                  {record.builtin ? <Tag className="ml-2" color="default">内置</Tag> : <Tag className="ml-2">自定义</Tag>}
                  {offPlatform.includes(value) ? <Tag className="ml-1" color="orange">平台未上架</Tag> : null}
                </span>
              ),
            },
            {
              title: "能力档",
              dataIndex: "profile",
              render: (value: string, record) => (
                <span className="text-xs text-[#4b5563]">
                  {profileLabel(value)}
                  {record.resolutions?.length ? ` · ${record.resolutions.join("/")}` : ""}
                </span>
              ),
            },
            {
              title: "消耗积分",
              dataIndex: "credit_cost",
              width: 104,
              render: (value: number | null) => (
                <span className="font-mono text-xs text-[#4b5563]">{typeof value === "number" ? `${value} / 张` : "未取到"}</span>
              ),
            },
            {
              title: "默认",
              dataIndex: "is_default",
              width: 88,
              render: (_, record) => (
                <Switch
                  checked={record.is_default}
                  onChange={(checked) => updateModel(record.workflow_id, { is_default: checked, enabled: checked ? true : record.enabled })}
                />
              ),
            },
          ]}
        />
      </section>

      <Modal
        title="手动添加生图模型"
        open={addOpen}
        onCancel={() => setAddOpen(false)}
        onOk={() => addModel.mutate()}
        confirmLoading={addModel.isPending}
        okText="添加"
        destroyOnHidden
      >
        <div className="space-y-3 pt-1">
          <p className="text-xs leading-5 text-[#6b7280]">
            仅用于添加平台清单之外的模型（例如刚下线但仍在用的历史模型）。常规情况请用「从平台拉取模型」。
          </p>
          <div>
            <label className="block text-xs font-medium text-[#4b5563]">上游模型 ID</label>
            <Input className="mt-1.5" value={newModelId} onChange={(event) => setNewModelId(event.target.value)} placeholder="nano-banana-2" />
          </div>
          <div>
            <label className="block text-xs font-medium text-[#4b5563]">显示名称</label>
            <Input className="mt-1.5" value={newDisplayName} onChange={(event) => setNewDisplayName(event.target.value)} placeholder="Nano Banana 2" />
          </div>
          <div>
            <label className="block text-xs font-medium text-[#4b5563]">能力档</label>
            <Select
              className="mt-1.5 w-full"
              value={newProfile}
              onChange={setNewProfile}
              options={catalogQuery.data?.profiles ?? []}
            />
          </div>
        </div>
      </Modal>

      <Modal
        title="GRS 平台在售生图模型"
        open={platformOpen}
        width={880}
        onCancel={() => setPlatformOpen(false)}
        onOk={() => importModels.mutate()}
        okText={selected.length ? `导入选中的 ${selected.length} 个模型` : "导入模型"}
        okButtonProps={{ disabled: selected.length === 0 }}
        confirmLoading={importModels.isPending}
        destroyOnHidden
      >
        <div className="space-y-3 pt-1">
          {platformNotice ? <Alert type="warning" showIcon message={platformNotice} /> : null}
          <p className="text-xs leading-5 text-[#6b7280]">
            清单来自上游 <code>GET /v1/models</code>（本次返回 {platformTotal} 个模型，其中生图 {platform.length} 个）。
            平台接口不含分辨率与画质参数，标记「需确认能力档」的新模型按名称家族推断，导入前请核对；已在目录中的模型不会被覆盖。
          </p>
          <Table
            rowKey="provider_model"
            size="small"
            pagination={false}
            scroll={{ y: 340 }}
            dataSource={platform}
            rowSelection={{
              selectedRowKeys: selected,
              onChange: (keys) => setSelected(keys as string[]),
              getCheckboxProps: (record) => ({ disabled: record.in_catalog }),
            }}
            columns={[
              {
                title: "上游模型 ID",
                dataIndex: "provider_model",
                width: 230,
                render: (value: string, record) => (
                  <div className="font-mono text-xs text-[#1f2937]">
                    {value}
                    {record.in_catalog ? <Tag className="ml-1">已在目录</Tag> : null}
                    {!record.in_catalog && record.profile_source === "guess" ? (
                      <Tag className="ml-1" color="orange">需确认能力档</Tag>
                    ) : null}
                  </div>
                ),
              },
              {
                title: "显示名称",
                width: 200,
                render: (_, record) => (record.in_catalog ? (
                  <span className="text-xs text-[#4b5563]">{record.display_name}</span>
                ) : (
                  <Input
                    size="small"
                    maxLength={80}
                    value={drafts[record.provider_model]?.display_name}
                    onChange={(event) => updateDraft(record.provider_model, { display_name: event.target.value })}
                  />
                )),
              },
              {
                title: "能力档",
                dataIndex: "profile",
                render: (value: string, record) => (record.in_catalog ? (
                  <span className="text-xs text-[#4b5563]">{profileLabel(value)}</span>
                ) : (
                  <Select
                    size="small"
                    className="w-full"
                    value={drafts[record.provider_model]?.profile}
                    onChange={(next) => updateDraft(record.provider_model, { profile: next })}
                    options={catalogQuery.data?.profiles ?? []}
                  />
                )),
              },
              {
                title: "消耗积分",
                dataIndex: "credit_cost",
                width: 96,
                render: (value: number | null) => (
                  <span className="font-mono text-xs text-[#4b5563]">{typeof value === "number" ? `${value} / 张` : "未标价"}</span>
                ),
              },
              {
                title: "启用",
                width: 72,
                render: (_, record) => (record.in_catalog ? (
                  <span className="text-xs text-[#6b7280]">{record.enabled ? "已启用" : "已停用"}</span>
                ) : (
                  <Switch
                    size="small"
                    checked={drafts[record.provider_model]?.enabled}
                    onChange={(checked) => updateDraft(record.provider_model, { enabled: checked })}
                  />
                )),
              },
            ]}
          />
        </div>
      </Modal>
    </main>
  )
}
