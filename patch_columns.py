import sys, os, re
path = "frontend/src/director2/panes/JobsCenterPane.tsx"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# Find the start of columns
start_idx = content.find('const columns: TableProps<Director2Job>["columns"] = [')
if start_idx == -1:
    print("Cannot find columns start")
    sys.exit(1)

# Find the end of columns. Look for '    ]' followed by something like 'const' or 'useEffect'
# Since the columns array is just a list, we can use a bracket matching approach.
brackets = 0
end_idx = -1
for i in range(start_idx + content[start_idx:].find('['), len(content)):
    if content[i] == '[':
        brackets += 1
    elif content[i] == ']':
        brackets -= 1
        if brackets == 0:
            end_idx = i + 1
            break

if end_idx == -1:
    print("Cannot find columns end")
    sys.exit(1)

new_columns = '''const latestJobsRef = useRef(jobs)
  useEffect(() => { latestJobsRef.current = jobs }, [jobs])

  const actionProps = useMemo(() => ({
    navigate, projectId, csrfToken, openDetail, handleUpscaleJob, upscalingJobId,
    getJobs: () => latestJobsRef.current,
    fetchJobs: () => { fetchJobsRef.current?.(false) },
    openContentDocument, openWorkshopDubbing, handleRetry
  }), [navigate, projectId, csrfToken, openDetail, handleUpscaleJob, upscalingJobId, openContentDocument, openWorkshopDubbing, handleRetry])

  const columns: TableProps<Director2Job>["columns"] = useMemo(() => [
    {
      title: "任务名称 / ID",
      key: "title",
      width: 280,
      render: (_, record) => (
        <div className="job-title-cell">
          <span className="job-name">{record.title}</span>
          <span className="job-id">{record.id}</span>
        </div>
      ),
    },
    {
      title: "状态",
      key: "status",
      width: 100,
      render: (_, record) => (
        <Tag color={getStatusTag(record.status).color}>{getStatusTag(record.status).text}</Tag>
      ),
    },
    {
      title: "进度",
      key: "progress",
      width: 180,
      render: (_, record) => (
        <Progress
          percent={record.progress}
          size="small"
          status={record.status === "failed" ? "exception" : record.progress === 100 ? "success" : "active"}
        />
      ),
    },
    {
      title: "结果",
      key: "result",
      width: 80,
      render: (_, record) => <JobResultCell record={record} openMediaPreview={openMediaPreview} />
    },
    { title: "创建时间", dataIndex: "created_at", width: 160 },
    {
      title: "操作",
      key: "action",
      width: 260,
      render: (_, record) => <JobActionCell record={record} actions={actionProps} />
    }
  ], [actionProps, openMediaPreview])'''

content = content[:start_idx] + new_columns + content[end_idx:]

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("Replaced successfully")
