import { useQuery } from "@tanstack/react-query"
import { Alert, Button, Descriptions, Drawer, Empty, Image, Space, Table, Tag, Typography } from "antd"
import { ListChecks, RefreshCw } from "lucide-react"
import { useMemo, useState } from "react"
import { listXiajiProjectJobs, type XiajiProjectJob } from "./xiaji-api"

const STATUS_TAG: Record<string, { color: string; text: string }> = {
  queued: { color: "default", text: "排队中" },
  running: { color: "processing", text: "进行中" },
  composing: { color: "processing", text: "合成中" },
  succeeded: { color: "green", text: "已完成" },
  partial: { color: "green", text: "部分完成" },
  failed: { color: "red", text: "失败" },
  interrupted: { color: "gold", text: "已中断" },
  cancelled: { color: "default", text: "已停止" },
  unknown: { color: "default", text: "未知" },
}

export const xiajiProjectJobsQueryKey = (projectId: string) => ["xiaji-project-jobs", projectId] as const

function statusTag(status: string, slot?: string) {
  if (slot === "compose" && (status === "running" || status === "queued")) {
    return <Tag color="processing">合成中</Tag>
  }
  const item = STATUS_TAG[status] || STATUS_TAG.unknown
  return <Tag color={item.color}>{item.text}</Tag>
}

function previewOf(row: XiajiProjectJob) {
  return row.preview_url || row.bound_url || row.outputs?.[0]?.cloud_url || row.outputs?.[0]?.download_url || ""
}

function isVideoPreview(row: XiajiProjectJob, src: string) {
  if (row.slot === "compose" || row.slot === "video") return true
  return /\.(mp4|webm|mov)(\?|$)/i.test(src)
}

function formatLlmOutput(value: unknown) {
  if (value && typeof value === "object" && !Array.isArray(value) && "raw" in value) {
    const raw = (value as { raw?: unknown }).raw
    if (typeof raw === "string" && raw.trim()) return raw
  }
  return formatParamValue(value)
}

function formatParamValue(value: unknown) {
  if (value == null || value === "") return "—"
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value)
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

export default function XiajiJobsModule({ projectId }: { projectId: string }) {
  const [openId, setOpenId] = useState<string | null>(null)
  const jobsQuery = useQuery({
    queryKey: xiajiProjectJobsQueryKey(projectId),
    queryFn: () => listXiajiProjectJobs(projectId),
    refetchInterval: (query) => {
      const rows = query.state.data || []
      return rows.some((item) => item.status === "queued" || item.status === "running") ? 2000 : 8000
    },
  })
  const rows = jobsQuery.data || []
  const selected = useMemo(() => rows.find((item) => item.id === openId) || null, [openId, rows])

  return (
    <div className="xiaji-jobs-page">
      <header className="xiaji-ingest-hero">
        <div className="xiaji-ingest-hero-icon" aria-hidden>
          <ListChecks size={18} />
        </div>
        <div className="xiaji-ingest-hero-copy">
          <div className="xiaji-ingest-hero-row">
            <h1>全部任务</h1>
            <Space>
              <Button icon={<RefreshCw size={14} />} onClick={() => jobsQuery.refetch()}>
                刷新
              </Button>
            </Space>
          </div>
          <p>当前项目里每次内容导入分析、生成脚本、声线定义、整集自动生成、合成成片，以及生图、草图、精绘和视频都会留下一条记录。点开可核对提示词、全部入参和结果。</p>
        </div>
      </header>
      {jobsQuery.isError ? <Alert type="error" showIcon message={(jobsQuery.error as Error).message} /> : null}
      {rows.length === 0 && !jobsQuery.isLoading ? (
        <Empty className="xiaji-placeholder" description="这个项目还没有任务" />
      ) : (
        <Table
          rowKey="id"
          size="small"
          pagination={{ pageSize: 12 }}
          dataSource={rows}
          onRow={(record) => ({ onClick: () => setOpenId(record.id) })}
          columns={[
            {
              title: "预览",
              width: 72,
              render: (_, record) => {
                const src = previewOf(record)
                if (!src) return "—"
                if (isVideoPreview(record, src)) {
                  return <video src={src} muted playsInline width={48} height={48} style={{ objectFit: "cover" }} />
                }
                return <Image src={src} width={48} height={48} style={{ objectFit: "cover" }} />
              },
            },
            { title: "标题", dataIndex: "title", ellipsis: true },
            { title: "槽位", dataIndex: "slot_label", width: 100 },
            { title: "绑定对象", dataIndex: "target", ellipsis: true },
            {
              title: "状态",
              width: 100,
              render: (_, record) => (
                <Space size={4}>
                  {statusTag(record.status, record.slot)}
                  {record.status === "running" || record.status === "queued" ? <span>{record.progress}%</span> : null}
                </Space>
              ),
            },
            { title: "任务 ID", dataIndex: "job_id", width: 140, ellipsis: true },
          ]}
        />
      )}
      <Drawer
        title={selected?.title || "任务详情"}
        open={Boolean(selected)}
        width={720}
        onClose={() => setOpenId(null)}
      >
        {selected ? (
          <Space direction="vertical" size={16} style={{ width: "100%" }}>
            <div>
              {statusTag(selected.status, selected.slot)}
              {selected.missing ? <Tag>任务记录缺失</Tag> : null}
            </div>
            <Descriptions
              size="small"
              bordered
              column={1}
              items={[
                { key: "slot", label: "槽位", children: `${selected.slot_label}（${selected.slot || "—"}）` },
                { key: "target", label: "对象", children: selected.target },
                { key: "job", label: "任务 ID", children: selected.job_id },
              ]}
            />
            {selected.error ? (
              <Alert
                type="error"
                showIcon
                message={selected.error}
                description={
                  selected.llm_output == null
                    ? "这次调用没有把模型原文落库。重新跑该任务后，返回内容会出现在下方。"
                    : "下方是模型当时返回的原文。"
                }
              />
            ) : null}

            {selected.llm_output != null ? (
              <Typography.Paragraph>
                <strong>模型返回内容</strong>
                <pre className="xiaji-job-prompt">{formatLlmOutput(selected.llm_output)}</pre>
              </Typography.Paragraph>
            ) : null}

            {selected.system_prompt ? (
              <Typography.Paragraph>
                <strong>系统提示词</strong>
                <pre className="xiaji-job-prompt">{selected.system_prompt}</pre>
              </Typography.Paragraph>
            ) : null}

            {selected.slot !== "compose" && selected.slot !== "auto_run" ? (
              <Typography.Paragraph>
                <strong>创作提示词</strong>
                <pre className="xiaji-job-prompt">{selected.prompt || "—"}</pre>
              </Typography.Paragraph>
            ) : null}

            {selected.negative_prompt ? (
              <Typography.Paragraph>
                <strong>负面提示词</strong>
                <pre className="xiaji-job-prompt">{selected.negative_prompt}</pre>
              </Typography.Paragraph>
            ) : null}

            <div>
              <Typography.Text strong>全部入参</Typography.Text>
              <Descriptions
                size="small"
                bordered
                column={1}
                className="xiaji-job-params"
                items={(selected.parameters || [])
                  .filter((item) => !["prompt", "user_prompt", "system_prompt", "response"].includes(item.name))
                  .map((item) => ({
                    key: item.name,
                    label: item.label,
                    children: (
                      <pre className="xiaji-job-param-value">{formatParamValue(item.value)}</pre>
                    ),
                  }))}
              />
            </div>

            {selected.slot === "compose" || selected.slot === "auto_run" ? null : (
            <Typography.Paragraph>
              <strong>传入参考图</strong>
              {(selected.reference_count || selected.references?.length || 0) > 0 ? (
                <div className="xiaji-job-refs">
                  <div>
                    已传入 {selected.reference_count || selected.references?.length} 张
                    {selected.slot === "reverse" ? "（REFERENCE 1 = 正面源图）" : ""}
                  </div>
                  <Image.PreviewGroup>
                    {(selected.references && selected.references.length > 0
                      ? selected.references
                      : Array.from({ length: selected.reference_count || 0 }, (_, index) => ({
                          index: index + 1,
                          url: `/api/jobs/${selected.job_id}/references/${index + 1}`,
                          label: `参考图 ${index + 1}`,
                        }))
                    ).map((item) => (
                      <Image
                        key={item.index}
                        src={item.url}
                        alt={item.label || `参考图 ${item.index}`}
                        width={120}
                        height={80}
                        style={{ objectFit: "cover" }}
                      />
                    ))}
                  </Image.PreviewGroup>
                </div>
              ) : (
                <div>没有传入参考图</div>
              )}
            </Typography.Paragraph>
            )}

            <Typography.Paragraph>
              <strong>回填 URL</strong>
              <br />
              {selected.bound_url || "尚未写回资产"}
            </Typography.Paragraph>
            <Typography.Paragraph>
              <strong>{selected.slot === "compose" ? "成片" : "回调预览"}</strong>
              <br />
              {previewOf(selected) ? (
                isVideoPreview(selected, previewOf(selected)) ? (
                  <video src={previewOf(selected)} controls playsInline style={{ maxWidth: "100%" }} />
                ) : (
                  <Image src={previewOf(selected)} />
                )
              ) : (
                "暂无输出"
              )}
            </Typography.Paragraph>
            {selected.outputs && selected.outputs.length > 0 ? (
              <Typography.Paragraph>
                <strong>输出</strong>
                {selected.outputs.map((output, index) => (
                  <span key={`${output.download_url || output.cloud_url || index}`}>
                    <br />
                    {output.kind || "file"}：{output.cloud_url || output.download_url || "—"}
                  </span>
                ))}
              </Typography.Paragraph>
            ) : null}
            <Typography.Paragraph type="secondary">
              创建：{selected.job_created_at || "—"}
              <br />
              更新：{selected.job_updated_at || "—"}
            </Typography.Paragraph>
          </Space>
        ) : null}
      </Drawer>
    </div>
  )
}
