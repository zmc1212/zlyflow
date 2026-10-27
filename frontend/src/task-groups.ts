export type CreatedAtTask = { created_at: string }
export type TaskTimeGroupKey = "today" | "yesterday" | "week" | "older"
export type TaskTimeGroup<T extends CreatedAtTask> = { key: TaskTimeGroupKey; label: string; tasks: T[] }

function localDayStart(ms: number) {
  const date = new Date(ms)
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()
}

function shiftLocalDays(ms: number, days: number) {
  const date = new Date(ms)
  return new Date(date.getFullYear(), date.getMonth(), date.getDate() + days).getTime()
}

export function groupTasksByCreatedAt<T extends CreatedAtTask>(tasks: T[], nowMs: number): TaskTimeGroup<T>[] {
  const todayStart = localDayStart(nowMs)
  const thresholds = [todayStart, shiftLocalDays(todayStart, -1), shiftLocalDays(todayStart, -6)]
  const buckets: TaskTimeGroup<T>[] = [
    { key: "today", label: "今天", tasks: [] },
    { key: "yesterday", label: "昨天", tasks: [] },
    { key: "week", label: "过去 7 天", tasks: [] },
    { key: "older", label: "更早", tasks: [] },
  ]
  tasks.forEach((task) => {
    const created = new Date(task.created_at).getTime()
    const index = Number.isNaN(created)
      ? 3
      : created >= thresholds[0]
        ? 0
        : created >= thresholds[1]
          ? 1
          : created >= thresholds[2]
            ? 2
            : 3
    buckets[index].tasks.push(task)
  })
  return buckets.filter((bucket) => bucket.tasks.length > 0)
}
