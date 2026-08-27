import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Alert, Button, Input, Modal, Select, Switch, Table, Tag, message } from "antd"
import { CheckCircle2, Cloud, KeyRound, Plus, RefreshCw, WalletCards } from "lucide-react"
import { useEffect, useMemo, useState } from "react"
import { jsonMutation, requestJson } from "../api"

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
}

type CatalogPayload = {
  models: CatalogModel[]
  profiles: { value: string; label: string }[]
}

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

  useEffect(() => {
    if (!query.data) return
    setEnabled(query.data.enabled)
    setBaseUrl(query.data.base_url)
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
    onSuccess: () => {
      setApiKey("")
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
  const test = useMutation({
    mutationFn: () => requestJson<ProviderConfig>("/api/admin/providers/grs/test", jsonMutation(csrfToken, {
      base_url: baseUrl,
      api_key: apiKey || null,
    })),
    onSuccess: () => {
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
  const error = save.error ?? saveModels.error ?? addModel.error ?? syncCatalog.error ?? test.error ?? balance.error ?? query.error ?? catalogQuery.error

  const updateModel = (workflowId: string, patch: Partial<CatalogModel>) => {
    setModels((current) => current.map((item) => {
      if (item.workflow_id !== workflowId) {
        return patch.is_default ? { ...item, is_default: false } : item
      }
      return { ...item, ...patch }
    }))
  }

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
            <h3 className="text-sm font-semibold text-[#111827]">生图模型目录</h3>
            <p className="mt-1 text-xs leading-5 text-[#6b7280]">
              勾选启用后会出现在创作页「选择工作流」。内置目录来自 GRS 文档，不会自动拉取上游列表。
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button icon={<Plus size={14} />} onClick={() => setAddOpen(true)}>添加模型</Button>
            <Button icon={<RefreshCw size={14} />} loading={syncCatalog.isPending} onClick={() => syncCatalog.mutate()}>
              同步内置目录
            </Button>
            <Button type="primary" loading={saveModels.isPending} onClick={() => saveModels.mutate(models)}>
              保存目录
            </Button>
          </div>
        </div>

        <Table
          className="mt-4"
          rowKey="workflow_id"
          size="middle"
          pagination={false}
          dataSource={models}
          columns={[
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
        title="添加生图模型"
        open={addOpen}
        onCancel={() => setAddOpen(false)}
        onOk={() => addModel.mutate()}
        confirmLoading={addModel.isPending}
        okText="添加"
        destroyOnHidden
      >
        <div className="space-y-3 pt-1">
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
    </main>
  )
}
