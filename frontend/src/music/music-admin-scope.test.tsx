import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"
import type { User } from "../api"
import { StudioThemeProvider } from "../ThemeProvider"
import type { MusicChat, MusicJob } from "./api"
import MusicChatRail from "./MusicChatRail"
import MusicWorkspace from "./MusicWorkspace"

const admin: User = {
  id: "admin-1", username: "zlyadmin", display_name: "管理员", role: "super_admin",
  is_active: true, must_change_password: false, created_at: "", updated_at: "",
}
const employee: User = {
  id: "emp-1", username: "worker", display_name: "小工", role: "employee",
  is_active: true, must_change_password: false, created_at: "", updated_at: "",
}

const chat = (patch: Partial<MusicChat> = {}): MusicChat => ({
  id: "chat-1", owner_user_id: "emp-1", title: "改《麦地》", anchor_job_id: null,
  created_at: "2026-11-08T01:00:00+00:00", updated_at: "2026-11-08T01:00:00+00:00", ...patch,
})

function renderRail(user: User, adminFilter: string, chats: MusicChat[]) {
  const client = new QueryClient()
  const isAdmin = user.role === "admin" || user.role === "super_admin"
  const scope = isAdmin && adminFilter !== user.id ? adminFilter : "mine"
  client.setQueryData(["music-chats", scope], chats)
  client.setQueryData(["music-jobs", scope], [])
  const html = renderToStaticMarkup(
    <MemoryRouter><QueryClientProvider client={client}>
      <MusicChatRail
        csrfToken=""
        user={user}
        adminUserOptions={[{ value: "all", label: "全部用户" }, { value: employee.id, label: "小工" }]}
        adminUserFilter={adminFilter}
        adminUserName="小工"
      />
    </QueryClientProvider></MemoryRouter>,
  )
  client.clear()
  return html
}

describe("music rail admin scope", () => {
  it("shows the user switcher and hides creation while an admin inspects another account", () => {
    const html = renderRail(admin, employee.id, [chat()])
    expect(html).toContain("切换查看用户")
    expect(html).toContain("正在只读查看")
    // 只读查看他人时不允许新建对话，也不显示对话重命名/删除入口
    expect(html).not.toContain("开始新对话")
    expect(html).not.toContain("对话操作")
  })

  it("keeps creation available for an admin in the all-users view", () => {
    const html = renderRail(admin, "all", [chat(), chat({ id: "chat-2", owner_user_id: "admin-1", title: "我的对话" })])
    expect(html).toContain("切换查看用户")
    expect(html).toContain("开始新对话")
    expect(html).not.toContain("正在只读查看")
  })

  it("does not expose the user switcher to regular employees", () => {
    const html = renderRail(employee, "all", [chat({ owner_user_id: "emp-1" })])
    expect(html).not.toContain("切换查看用户")
    expect(html).not.toContain("正在只读查看")
    expect(html).toContain("开始新对话")
  })
})

const job = (patch: Partial<MusicJob> = {}): MusicJob => ({
  id: "song-1", owner_user_id: "emp-1", title: "麦地", style: "folk, male vocal, 82 BPM", lyrics: "",
  status: "succeeded", progress: 100, params: {}, result_url: "/one.flac", result_format: "flac",
  cover_url: null, duration_seconds: 182, remote_job_id: null, remote_song_id: null, error_message: null,
  chat_id: null, created_at: "2026-11-08T01:00:00+00:00", updated_at: "2026-11-08T01:00:00+00:00", completed_at: null,
  ...patch,
})

describe("music workspace admin scope", () => {
  it("renders the read-only library view for an admin inspecting another account", () => {
    const client = new QueryClient()
    client.setQueryData(["music-jobs", "emp-1"], [job()])
    client.setQueryData(["music-status"], { configured: true, base_url: "http://x", credential_ready: true })
    const html = renderToStaticMarkup(
      <MemoryRouter initialEntries={["/music?view=library"]}>
        <QueryClientProvider client={client}>
          <StudioThemeProvider>
            <MusicWorkspace csrfToken="" user={admin} adminUserFilter="emp-1" adminUserName="小工" />
          </StudioThemeProvider>
        </QueryClientProvider>
      </MemoryRouter>,
    )
    client.clear()
    expect(html).toContain("小工 的歌曲")
    expect(html).toContain("正在只读查看 小工 的歌曲")
    expect(html).toContain("麦地")
  })
})
