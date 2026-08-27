import { useQuery, useQueryClient } from "@tanstack/react-query"
import { message } from "antd"
import { useState } from "react"
import { User } from "../api"
import { DirectoryHandleLike } from "../local-resource-store"
import DirectorBatchStudio from "./DirectorBatchStudio"
import DirectorHome from "./DirectorHome"
import DirectorRecipeStudio from "./DirectorRecipeStudio"
import {
  convertDirectorProjectToRecipe, copyDirectorProject, createDirectorProjectRecord,
  deleteDirectorProject, listDirectorProjects, DirectorProjectListItem,
} from "./director-api"
import { createEmptyBatch, createEmptyRecipe } from "./types"

interface DirectorStudioModuleProps {
  user: User
  csrfToken: string
  allJobs: any[]
  directoryHandle?: DirectoryHandleLike
  onOpenDirectoryModal?: () => void
  onExitDirector?: () => void
}

type StudioView = "home" | "recipe" | "batch"

export default function DirectorStudioModule({
  user,
  csrfToken,
  allJobs,
  onExitDirector,
}: DirectorStudioModuleProps) {
  const queryClient = useQueryClient()
  const [view, setView] = useState<StudioView>("home")
  const [activeProjectId, setActiveProjectId] = useState<string | null>(null)

  const listQuery = useQuery({
    queryKey: ["director-projects"],
    queryFn: listDirectorProjects,
  })

  async function refreshList() {
    await queryClient.invalidateQueries({ queryKey: ["director-projects"] })
  }

  async function handleCreateDirector() {
    try {
      const created = await createDirectorProjectRecord({
        title: "未命名导演工程",
        summary: "",
        source_script: "",
        payload: createEmptyRecipe(),
      }, csrfToken)
      setActiveProjectId(created.id)
      setView("recipe")
      await refreshList()
    } catch (error) {
      message.error(error instanceof Error ? error.message : "创建失败")
    }
  }

  async function handleCreateBatch() {
    try {
      const created = await createDirectorProjectRecord({
        title: "批量短视频",
        summary: "",
        source_script: "",
        payload: createEmptyBatch(),
      }, csrfToken)
      setActiveProjectId(created.id)
      setView("batch")
      await refreshList()
    } catch (error) {
      message.error(error instanceof Error ? error.message : "创建失败")
    }
  }

  async function handleOpen(item: DirectorProjectListItem) {
    try {
      if (item.kind === "batch_run") {
        setActiveProjectId(item.id)
        setView("batch")
        return
      }
      if (item.kind === "timeline") {
        const converted = await convertDirectorProjectToRecipe(item.id, csrfToken)
        setActiveProjectId(converted.id)
        setView("recipe")
        await refreshList()
        message.info("已将旧时间轴转为 Recipe")
        return
      }
      setActiveProjectId(item.id)
      setView("recipe")
    } catch (error) {
      message.error(error instanceof Error ? error.message : "打开失败")
    }
  }

  async function handleCopy(projectId: string) {
    try {
      await copyDirectorProject(projectId, csrfToken)
      await refreshList()
      message.success("已复制工程")
    } catch (error) {
      message.error(error instanceof Error ? error.message : "复制失败")
    }
  }

  async function handleDelete(projectId: string) {
    try {
      await deleteDirectorProject(projectId, csrfToken)
      if (activeProjectId === projectId) {
        setActiveProjectId(null)
        setView("home")
      }
      await refreshList()
    } catch (error) {
      message.error(error instanceof Error ? error.message : "删除失败")
    }
  }

  return (
    <div className="director-shell">
      {view === "home" || !activeProjectId ? (
        <DirectorHome
          items={listQuery.data || []}
          loading={listQuery.isLoading}
          onCreateDirector={handleCreateDirector}
          onCreateBatch={handleCreateBatch}
          onOpen={handleOpen}
          onCopy={handleCopy}
          onDelete={handleDelete}
          onExitDirector={onExitDirector}
        />
      ) : view === "batch" ? (
        <DirectorBatchStudio
          projectId={activeProjectId}
          csrfToken={csrfToken}
          allJobs={allJobs}
          onBack={() => { setView("home"); void refreshList() }}
          onExitDirector={onExitDirector}
        />
      ) : (
        <DirectorRecipeStudio
          projectId={activeProjectId}
          csrfToken={csrfToken}
          user={user}
          allJobs={allJobs}
          onBack={() => { setView("home"); void refreshList() }}
          onExitDirector={onExitDirector}
        />
      )}
    </div>
  )
}
