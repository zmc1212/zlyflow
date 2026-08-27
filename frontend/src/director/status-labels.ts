export function directorStatusLabel(status: string | undefined): string {
  if (status === "queued") return "排队中"
  if (status === "running") return "生成中"
  if (status === "succeeded") return "已完成"
  if (status === "failed") return "失败"
  if (status === "interrupted") return "已中断"
  if (status === "cancelled") return "已停止"
  return "待生成"
}

export function directorStatusColor(status: string | undefined): string {
  if (status === "completed" || status === "succeeded") return "success"
  if (status === "running" || status === "queued") return "processing"
  if (status === "failed") return "error"
  if (status === "interrupted" || status === "cancelled") return "warning"
  return "default"
}

export function isDirectorFailedStatus(status: string | undefined): boolean {
  return status === "failed" || status === "interrupted" || status === "cancelled"
}
