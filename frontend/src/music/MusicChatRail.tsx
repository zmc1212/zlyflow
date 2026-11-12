import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Dropdown, Input, Modal, Select, message } from "antd"
import { CheckCircle2, CircleAlert, Clock3, LoaderCircle, MoreHorizontal, Music2, Pencil, Search, SquarePen, Trash2 } from "lucide-react"
import { useMemo, useState } from "react"
import { useLocation, useNavigate } from "react-router-dom"
import type { User } from "../api"
import type { MusicChat, MusicJob } from "./api"
import { deleteMusicChat, fetchMusicChats, fetchMusicJobs, renameMusicChat } from "./api"
import { searchFilterOption } from "../search-match"
import { musicArtworkUrl, musicCanManage, musicReadOnlyScope, musicScopedUserId, musicTimeFull, musicTimeShort } from "./music-library"
import { groupTasksByCreatedAt } from "../task-groups"
import { musicChatPath, parseMusicPath } from "../paths"

const STATUS_LABEL: Record<string, string> = {
  queued: "排队中", running: "生成中", succeeded: "已完成", failed: "生成失败",
}

/** 音乐页左栏对话列表：对齐生成页任务栏的视觉与交互（新对话/搜索/时间分组/重命名/删除）。 */
export default function MusicChatRail({ csrfToken, user, adminUserOptions = [], adminUserFilter = "all", adminUserName = "", onAdminUserChange }: {
  csrfToken: string
  user: User | null
  adminUserOptions?: { value: string; label: string }[]
  adminUserFilter?: string
  adminUserName?: string
  onAdminUserChange?: (value: string) => void
}) {
  const navigate = useNavigate()
  const location = useLocation()
  const queryClient = useQueryClient()
  const [modal, modalContext] = Modal.useModal()
  const { chatId: selectedId } = parseMusicPath(location.pathname)
  const [search, setSearch] = useState("")
  const [renaming, setRenaming] = useState<MusicChat | null>(null)
  const [renameValue, setRenameValue] = useState("")
  // 管理员可切换查看其他账号的对话与歌曲；普通账号始终只看本人。
  const isAdminViewer = user?.role === "admin" || user?.role === "super_admin"
  const scopedUserId = musicScopedUserId(user?.role, adminUserFilter, user?.id)
  const readOnlyScope = musicReadOnlyScope(user?.role, adminUserFilter, user?.id)
  const manageable = (chat: MusicChat) => musicCanManage(chat.owner_user_id, user?.id, readOnlyScope)

  const chatsQuery = useQuery({ queryKey: ["music-chats", scopedUserId ?? "mine"], queryFn: () => fetchMusicChats(scopedUserId), refetchInterval: 15000 })
  const jobsQuery = useQuery({ queryKey: ["music-jobs", scopedUserId ?? "mine"], queryFn: () => fetchMusicJobs(scopedUserId) })
  const chats = chatsQuery.data ?? []
  const jobs = jobsQuery.data ?? []
  const anchorByChat = useMemo(() => {
    const map = new Map<string, MusicJob>()
    for (const chat of chatsQuery.data ?? []) {
      if (!chat.anchor_job_id) continue
      const job = jobs.find((item) => item.id === chat.anchor_job_id)
      if (job) map.set(chat.id, job)
    }
    return map
  }, [chatsQuery.data, jobs])

  const removeChat = useMutation({
    mutationFn: (chatId: string) => deleteMusicChat(csrfToken, chatId).then(() => chatId),
    onSuccess: (chatId) => {
      void queryClient.invalidateQueries({ queryKey: ["music-chats"] })
      if (parseMusicPath(window.location.pathname).chatId === chatId) navigate(musicChatPath())
      message.success("已删除对话")
    },
    onError: (error) => message.error(error instanceof Error ? error.message : "删除失败"),
  })

  const renameChat = useMutation({
    mutationFn: ({ chatId, title }: { chatId: string; title: string }) => renameMusicChat(csrfToken, chatId, title),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["music-chats"] })
      setRenaming(null)
      message.success("已重命名")
    },
    onError: (error) => message.error(error instanceof Error ? error.message : "重命名失败"),
  })

  const needle = search.trim().toLocaleLowerCase()
  const filtered = (chatsQuery.data ?? []).filter((chat) => !needle || chat.title.toLocaleLowerCase().includes(needle))
  const groups = groupTasksByCreatedAt(filtered.map((chat) => ({ ...chat, created_at: chat.created_at ?? "" })), Date.now())

  const confirmRemove = (chat: MusicChat) => {
    modal.confirm({
      title: `删除对话「${chat.title}」？`,
      content: "对话记录将被删除，已生成的歌曲仍保留在曲库。",
      okText: "删除", cancelText: "保留", okButtonProps: { danger: true },
      onOk: () => removeChat.mutateAsync(chat.id).catch(() => undefined),
    })
  }

  return <div className="flex min-h-0 flex-1 flex-col">
    {modalContext}
    <div className="border-b border-black/[0.05] px-4 pb-3 pt-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-[#171a1f]">音乐对话</p>
          {chats.length > 0 && <p className="mt-1 text-[11px] text-[#7c8794]">{chats.length} 条对话</p>}
        </div>
        {readOnlyScope ? null : <button type="button" onClick={() => navigate(musicChatPath())} title="开始新对话"
          className="grid size-8 place-items-center rounded-lg text-[#65707c] transition hover:bg-black/[0.04] hover:text-[#171a1f]">
          <SquarePen size={16} />
        </button>}
      </div>
      {isAdminViewer && <Select className="studio-task-user-select mt-3" aria-label="切换查看用户" value={adminUserFilter} showSearch filterOption={searchFilterOption} options={adminUserOptions} onChange={onAdminUserChange} />}
      {readOnlyScope ? <p className="mt-3 text-[11px] leading-5 text-[#7c8794]">正在只读查看 {adminUserName || "该用户"} 的对话</p> : null}
      <Input className="mt-3" size="small" aria-label="搜索音乐对话" placeholder="搜索对话" prefix={<Search size={14} />}
        allowClear value={search} onChange={(event) => setSearch(event.target.value)} />
    </div>
    <div className="studio-music-rail-scroll min-h-0 flex-1 overflow-y-auto pb-4 pt-2">
      {filtered.length === 0 && <p className="px-4 py-6 text-center text-xs text-[#98a2ad]">
        {chats.length ? "没有匹配的对话" : readOnlyScope ? "该用户还没有对话" : "还没有对话，从右侧开始创作"}
      </p>}
      {groups.map((group) => <section key={group.label} className="studio-task-section">
        <p className="studio-task-section-title">{group.label}</p>
        {group.tasks.map((chat) => {
          const anchor = anchorByChat.get(chat.id)
          const selected = chat.id === selectedId
          const title = chat.title || "新对话"
          const updatedFull = musicTimeFull(chat.updated_at)
          const statusIcon = !anchor ? null
            : anchor.status === "succeeded" ? <CheckCircle2 size={13} aria-hidden />
              : anchor.status === "running" ? <LoaderCircle size={13} className="animate-spin" aria-hidden />
                : anchor.status === "failed" ? <CircleAlert size={13} aria-hidden />
                  : <Clock3 size={13} aria-hidden />
          const statusLabel = anchor ? STATUS_LABEL[anchor.status] ?? anchor.status : ""
          return <div key={chat.id} className="px-2 pb-1">
            <div
              role="button" tabIndex={0}
              onClick={() => navigate(musicChatPath(chat.id))}
              onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); navigate(musicChatPath(chat.id)) } }}
              className={`group relative flex h-9 w-full cursor-pointer items-center gap-2 rounded-lg px-2 text-left outline-none transition ${selected ? "studio-music-rail-row-selected" : "hover:bg-black/[0.035]"}`}
            >
              <span className="flex size-8 flex-none items-center justify-center overflow-hidden rounded-md bg-[#eef1f4]">
                {anchor
                  ? <img src={musicArtworkUrl(anchor)} alt="" className="size-8 object-cover" />
                  : <Music2 size={14} className="text-[#a0a8b2]" />}
              </span>
              {statusIcon && <span role="img" aria-label={statusLabel} title={statusLabel} className={`studio-task-state studio-task-state-${anchor?.status}`}>{statusIcon}</span>}
              <p title={title} className="min-w-0 flex-1 truncate text-sm leading-[21px] text-[#171a1f]">{title}</p>
              <span title={updatedFull ? `最近更新 ${updatedFull}` : undefined} className="shrink-0 text-[10px] tabular-nums text-[#7c8794]">{musicTimeShort(chat.updated_at)}</span>
              {manageable(chat) && <Dropdown trigger={["click"]} placement="bottomRight" menu={{
                items: [
                  { key: "rename", icon: <Pencil size={14} />, label: "重命名" },
                  { type: "divider" as const },
                  { key: "delete", danger: true, icon: <Trash2 size={14} />, label: "删除" },
                ],
                onClick: ({ key, domEvent }) => {
                  domEvent.stopPropagation()
                  if (key === "rename") { setRenaming(chat); setRenameValue(chat.title) }
                  else if (key === "delete") confirmRemove(chat)
                },
              }}>
                <button type="button" title="对话操作" aria-label={`对话操作：${title}`} onClick={(event) => event.stopPropagation()}
                  className="grid size-7 shrink-0 place-items-center rounded-md text-[#65707c] opacity-0 transition hover:bg-white hover:text-[#171a1f] group-hover:opacity-100 group-focus-within:opacity-100 focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#4d6bfe]/30">
                  <MoreHorizontal size={16} />
                </button>
              </Dropdown>}
            </div>
          </div>
        })}
      </section>)}
    </div>
    <Modal open={Boolean(renaming)} title="重命名对话" onCancel={() => setRenaming(null)} okText="保存" cancelText="取消"
      okButtonProps={{ disabled: !renameValue.trim() || renameChat.isPending }}
      onOk={() => renaming && renameChat.mutateAsync({ chatId: renaming.id, title: renameValue.trim() }).catch(() => undefined)} destroyOnHidden>
      <Input aria-label="对话名称" value={renameValue} maxLength={120} onChange={(event) => setRenameValue(event.target.value)}
        onPressEnter={() => renaming && renameValue.trim() && renameChat.mutateAsync({ chatId: renaming.id, title: renameValue.trim() }).catch(() => undefined)} />
    </Modal>
  </div>
}
