import { createEmptyProject, createEmptyShot, createInitialSubjectSlots, defaultCameraDirection, DirectorShot, SubjectSlot, TimelineProject } from "./types"

const STORAGE_PREFIX = "zly_ai_director_projects_"
const MIGRATED_PREFIX = "zly_ai_director_projects_migrated_"

function persistableDataUrl(value: string | undefined): string | undefined {
  return value?.startsWith("data:") ? value : undefined
}

function persistableHttpUrl(value: string | undefined): string | undefined {
  if (!value || value.startsWith("data:")) return undefined
  return value
}

function persistableSlot(slot: SubjectSlot, keepDataUrl: boolean): SubjectSlot {
  const { file: _file, analyzing: _analyzing, ...rest } = slot
  return {
    ...rest,
    previewUrl: keepDataUrl ? persistableDataUrl(slot.previewUrl) : persistableHttpUrl(slot.previewUrl),
  }
}

function persistableShot(shot: DirectorShot, keepDataUrl: boolean): DirectorShot {
  const { firstFrameFile: _first, endFrameFile: _end, ...rest } = shot
  return {
    ...rest,
    firstFrameUrl: keepDataUrl ? persistableDataUrl(shot.firstFrameUrl) : persistableHttpUrl(shot.firstFrameUrl),
    endFrameUrl: keepDataUrl ? persistableDataUrl(shot.endFrameUrl) : persistableHttpUrl(shot.endFrameUrl),
    takes: (shot.takes || []).map((take) => ({ ...take })),
  }
}

export function persistableDirectorProjects(projects: TimelineProject[]): TimelineProject[] {
  return projects.map((project) => persistableTimelineProject(project, true))
}

export function persistableTimelineProject(project: TimelineProject, keepDataUrl = false): TimelineProject {
  return {
    ...project,
    subjectSlots: (project.subjectSlots || []).map((slot) => persistableSlot(slot, keepDataUrl)),
    shots: (project.shots || []).map((shot) => persistableShot(shot, keepDataUrl)),
  }
}

export function createExampleProject(): TimelineProject {
  const now = new Date().toISOString()
  return {
    ...createEmptyProject("示例：城市晨光三镜"),
    summary: "用三条演示分镜熟悉时间轴，可随时删除",
    shots: [
      {
        ...createEmptyShot(1, 0, 5),
        title: "场景起势全景",
        prompt: "电影级城市远景，晨光洒在建筑群上，镜头平稳向前推进",
        camera: { ...defaultCameraDirection(), scale: "WS", movement: "zoom_in" },
      },
      {
        ...createEmptyShot(2, 5, 5),
        title: "主体中景动作",
        prompt: "主角缓步走在街道上，侧光微风，神态坚毅",
        camera: { ...defaultCameraDirection(), scale: "MS", movement: "tracking" },
      },
      {
        ...createEmptyShot(3, 10, 5),
        title: "情绪焦点特写",
        prompt: "人物面部特写，眼神专注注视前方，浅景深虚化背景",
        camera: { ...defaultCameraDirection(), scale: "CU", movement: "static", lighting: "dramatic_low_key" },
      },
    ],
    createdAt: now,
    updatedAt: now,
  }
}

/** @deprecated Use createEmptyProject — blank projects no longer seed three demo shots. */
export function createDefaultProject(): TimelineProject {
  return createEmptyProject()
}

function migrateLegacyProject(raw: Record<string, unknown>): TimelineProject {
  const base = createEmptyProject()
  const shots = Array.isArray(raw.shots)
    ? raw.shots.map((item: any, idx: number) => ({
        ...createEmptyShot(idx + 1, idx * 5, item?.durationSec || 5),
        ...item,
        takes: Array.isArray(item?.takes) ? item.takes : [],
        activeTakeIndex: typeof item?.activeTakeIndex === "number" ? item.activeTakeIndex : 0,
        durationSec: typeof item?.durationSec === "number" ? item.durationSec : 5,
        referencedSubjectIds: Array.isArray(item?.referencedSubjectIds) ? item.referencedSubjectIds : [],
      }))
    : base.shots
  return {
    ...base,
    ...raw,
    sourceScript: typeof raw.sourceScript === "string" ? raw.sourceScript : "",
    styleVibe: typeof raw.styleVibe === "string" ? raw.styleVibe : undefined,
    requestedShotCount: typeof raw.requestedShotCount === "number" ? raw.requestedShotCount : undefined,
    subjectSlots: Array.isArray(raw.subjectSlots) ? raw.subjectSlots as SubjectSlot[] : createInitialSubjectSlots(),
    canvasTier: (raw.canvasTier as TimelineProject["canvasTier"]) || "native",
    previewQuality: (raw.previewQuality as TimelineProject["previewQuality"]) || base.previewQuality,
    previewSpeed: (raw.previewSpeed as TimelineProject["previewSpeed"]) || base.previewSpeed,
    finalQuality: (raw.finalQuality as TimelineProject["finalQuality"]) || (
      raw.canvasTier === "past_native" ? "2.0" : raw.canvasTier === "fast" ? "0.4" : base.finalQuality
    ),
    finalSpeed: (raw.finalSpeed as TimelineProject["finalSpeed"]) || base.finalSpeed,
    weightProfile: raw.weightProfile === "pruned" ? "pruned" : "full",
    fps: typeof raw.fps === "number" ? raw.fps : 24,
    refsMode: (raw.refsMode as TimelineProject["refsMode"]) || "refs_on",
    shots,
  }
}

export function peekLocalDirectorProjects(userId: string): TimelineProject[] {
  try {
    const raw = localStorage.getItem(`${STORAGE_PREFIX}${userId}`)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed) || parsed.length === 0) return []
    return parsed.map((item: Record<string, unknown>) => migrateLegacyProject(item))
  } catch (error) {
    console.error("读取本地导演工程失败:", error)
    return []
  }
}

export function loadDirectorProjects(userId: string): TimelineProject[] {
  return peekLocalDirectorProjects(userId)
}

export function saveDirectorProjects(userId: string, projects: TimelineProject[]): void {
  try {
    localStorage.setItem(`${STORAGE_PREFIX}${userId}`, JSON.stringify(persistableDirectorProjects(projects)))
  } catch (error) {
    console.error("保存导演项目失败:", error)
  }
}

export function hasDirectorProjectsMigrated(userId: string): boolean {
  try {
    return localStorage.getItem(`${MIGRATED_PREFIX}${userId}`) === "1"
  } catch {
    return false
  }
}

export function markDirectorProjectsMigrated(userId: string): void {
  try {
    localStorage.setItem(`${MIGRATED_PREFIX}${userId}`, "1")
  } catch (error) {
    console.error("标记导演工程迁库失败:", error)
  }
}
