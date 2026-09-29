import sys, os
path = "frontend/src/director2/panes/JobsCenterPane.tsx"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

import re

match = re.search(r"export default function JobsCenterPane", content)
insert_pos = match.start()

# Find and replace the broken JobResultCell and JobActionCell
broken_start = content.rfind("const JobResultCell =")
if broken_start != -1:
    content = content[:broken_start] + content[insert_pos:]
    insert_pos = broken_start

new_components = """
const JobResultCell = memo(function JobResultCell({ record, openMediaPreview }: { record: Director2Job, openMediaPreview: any }) {
  const previewUrl = isVideoJob(record) ? jobPreviewVideoUrl(record) : record.result_url
  const upscaled = isVideoJob(record) && Boolean(jobUpscaledVideoUrl(record))
  const scaleTag = jobUpscaleScale(record)
  return previewUrl ? (
    isTtsJob(record) ? (
      <audio src={record.result_url ?? undefined} className="result-thumb" preload="metadata" controls />
    ) : (
    <button
      type="button"
      className="result-thumb-btn"
      aria-label={upscaled ? `预览 ${scaleTag} 超分结果` : "预览结果"}
      onClick={() => openMediaPreview({
        src: previewUrl,
        kind: record.job_type === "video_generation" || record.job_type === "action_previs" ? "video" : "image",
        title: upscaled ? `${record.title || "生成结果"} · ${scaleTag}` : record.title || "生成结果",
      })}
    >
      {record.job_type === "video_generation" || record.job_type === "action_previs" ? (
        <>
          <video src={previewUrl} className="result-thumb" muted preload="none" />
          {upscaled ? <Tag color="purple" className="result-upscale-tag">{scaleTag}</Tag> : null}
        </>
      ) : (
        <img src={record.result_url ?? undefined} className="result-thumb" alt="结果" />
      )}
    </button>
    )
  ) : record.job_type === "workshop_prompt" && record.status === "completed" ? (
    <Tag color="cyan">候选已生成 · 工坊查看</Tag>
  ) : isH3PromptJob(record) && (record.status === "completed" || record.status === "succeeded") ? (
    <Tag color="cyan">提示词就绪</Tag>
  ) : record.job_type === "prompt_expansion" && (record.status === "completed" || record.status === "succeeded") ? (
    <Tag color="green">预览已校正</Tag>
  ) : isShotPlanJob(record) && (record.status === "completed" || record.status === "succeeded") ? (
    <Tag color="purple">镜头已规划</Tag>
  ) : isTtsJob(record) && (record.status === "completed" || record.status === "succeeded") ? (
    <Tag color="green">配音就绪</Tag>
  ) : isShotPlanJob(record) && ["queued", "preparing", "running"].includes(record.status) ? (
    <Tag color="processing">规划中</Tag>
  ) : (
    <span className="text-muted">—</span>
  )
})

const JobActionCell = memo(function JobActionCell({ record, actions }: { record: Director2Job, actions: any }) {
  const { navigate, projectId, csrfToken, openDetail, handleUpscaleJob, upscalingJobId, getJobs, fetchJobs, openContentDocument, openWorkshopDubbing, handleRetry, jobUpscaleDisabledReason, jobUpscaleHint, jobCanShowUpscaleAction } = actions
  const jobs = getJobs()
  return (
    <Space>
      <Button size="small" type="primary" ghost onClick={() => openDetail(record)}>
        查看详情
      </Button>
      {jobCanShowUpscaleAction(record) ? (
        <UpscaleScaleButton
          disabled={Boolean(jobUpscaleDisabledReason(record, jobs)) || upscalingJobId === record.id}
          loading={upscalingJobId === record.id}
          hint={jobUpscaleDisabledReason(record, jobs) || jobUpscaleHint(record)}
          onSelect={(scale: number) => void handleUpscaleJob(record, scale)}
          ariaLabel={`超分 ${record.title || record.id}`}
        />
      ) : null}
      {record.payload?.episode_id && !isTtsJob(record) ? <Button size="small" type="link" onClick={() => navigate(director2WorkshopEpisodePath(projectId, String(record.payload?.episode_id), "shots"))}>打开工坊</Button> : null}
      {["workshop_planning", "workshop_prompt"].includes(record.job_type) && ["queued", "running"].includes(record.status) && <Button size="small" type="link" onClick={async () => {
        try { await actWorkshop(csrfToken, projectId, String(record.payload?.episode_id), record.id, {action:"cancel"}); await fetchJobs() }
        catch (err) { message.error(director2ErrorDetail(err,"取消任务失败")) }
      }}>取消</Button>}
      {(isShotPlanJob(record) || record.job_type === "script_development") && shotPlanDocumentId(record) ? (
        <Button size="small" type="link" onClick={() => openContentDocument(record)}>
          打开文档
        </Button>
      ) : null}
      {isTtsJob(record) && record.payload?.episode_id ? (
        <Button size="small" type="link" onClick={() => openWorkshopDubbing(record)}>
          打开配音
        </Button>
      ) : null}
      {record.status === "failed" && record.job_type !== "script_development" ? (
        <Button size="small" type="link" onClick={() => handleRetry(record.id)}>
          重试
        </Button>
      ) : null}
    </Space>
  )
})

"""

content = content[:insert_pos] + new_components + content[insert_pos:]

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("done")
