import { useEffect, useRef, useState, type RefObject } from "react"
import { updateDirectorProjectRecord } from "./director-api"
import { readDirectorContentConflict, type DirectorContentConflict } from "./director-project-controller"
import type { RecipeProject } from "./recipe-model"
type SaveStatus = "idle" | "saving" | "saved" | "failed"

/** Single project save queue, shared by editing, generation and conflict resolution. */
export function useDirectorProjectSession({ projectId, csrfToken, recipeRef, goalRef, runStartedAtRef, deletedTakeIdsRef, notifyFailure }: {
  projectId: string; csrfToken: string; recipeRef: RefObject<RecipeProject>; goalRef: RefObject<string>
  runStartedAtRef: RefObject<number>; deletedTakeIdsRef: RefObject<Set<string>>
  notifyFailure: (error: unknown, fallback: string) => void
}) {
  const [saveStatus, setSaveStatus] = useState<SaveStatus>("idle")
  const [contentConflict, setContentConflict] = useState<DirectorContentConflict | null>(null)
  const saveTimerRef = useRef<number | null>(null)
  const projectRevisionRef = useRef(0)
  const contentRevisionRef = useRef(0)
  const editVersionRef = useRef(0)
  const savedEditVersionRef = useRef(0)
  const saveInFlightRef = useRef<Promise<boolean> | null>(null)
  const conflictRef = useRef<DirectorContentConflict | null>(null)
  useEffect(() => () => { if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current) }, [])
  async function persistNow(_next = recipeRef.current, extra?: { title?: string; source_script?: string }) {
    if (runStartedAtRef.current) return true
    if (conflictRef.current) return false
    if (saveInFlightRef.current) await saveInFlightRef.current
    if (runStartedAtRef.current) return true
    if (conflictRef.current) return false

    const snapshot = recipeRef.current
    const snapshotEditVersion = editVersionRef.current
    const request = (async () => {
      setSaveStatus("saving")
      try {
        const row = await updateDirectorProjectRecord(projectId, {
          title: extra?.title?.trim() || snapshot.script.title.trim() || "未命名导演工程",
          summary: snapshot.script.summary,
          source_script: extra?.source_script ?? goalRef.current,
          payload: snapshot,
          deleted_take_ids: Array.from(deletedTakeIdsRef.current),
          ...(contentRevisionRef.current > 0
            ? { expected_content_revision: contentRevisionRef.current }
            : {}),
        }, csrfToken)
        projectRevisionRef.current = row.revision
        contentRevisionRef.current = row.content_revision
        savedEditVersionRef.current = Math.max(savedEditVersionRef.current, snapshotEditVersion)
        setSaveStatus(editVersionRef.current === snapshotEditVersion ? "saved" : "idle")
        return true
      } catch (error) {
        const remote = readDirectorContentConflict(error)
        if (remote) {
          const conflict = { remote }
          conflictRef.current = conflict
          setContentConflict(conflict)
          setSaveStatus("failed")
          return false
        }
        setSaveStatus("failed")
        notifyFailure(error, "保存失败")
        return false
      }
    })()
    saveInFlightRef.current = request
    try {
      return await request
    } finally {
      if (saveInFlightRef.current === request) saveInFlightRef.current = null
    }
  }

  function scheduleSave() {
    editVersionRef.current += 1
    if (runStartedAtRef.current || conflictRef.current) return
    if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current)
    saveTimerRef.current = window.setTimeout(() => {
      saveTimerRef.current = null
      void persistNow()
    }, 800)
  }

  async function flushSave() {
    if (saveTimerRef.current) {
      window.clearTimeout(saveTimerRef.current)
      saveTimerRef.current = null
    }
    return persistNow()
  }
  return { saveStatus, setSaveStatus, contentConflict, setContentConflict, saveTimerRef, projectRevisionRef, contentRevisionRef, editVersionRef, savedEditVersionRef, conflictRef, persistNow, scheduleSave, flushSave }
}
