import type { Location } from "react-router-dom"
import type { AuthStatus, UserRole } from "./api"

export const PATHS = {
  home: "/",
  login: "/login",
  setup: "/setup",
  password: "/password",
  generateImage: "/generate/image",
  generateVideo: "/generate/video",
  director: "/director",
  assets: "/assets",
  admin: "/admin",
  adminAccounts: "/admin/accounts",
  adminProviders: "/admin/providers",
  adminLlm: "/admin/llm",
  adminStorage: "/admin/storage",
} as const

export const ROUTE_PATTERNS = {
  generateImageJob: "/generate/image/:jobId",
  generateVideoJob: "/generate/video/:jobId",
  directorProject: "/director/:projectId",
  directorBatch: "/director/batch/:projectId",
  adminTab: "/admin/:tab",
} as const

export const ADMIN_TABS = ["accounts", "providers", "llm", "storage"] as const
export type AdminTab = (typeof ADMIN_TABS)[number]
export const SUPER_ADMIN_ONLY_TABS: readonly AdminTab[] = ["providers", "llm", "storage"]

const AUTH_SCREEN_PATHS = new Set<string>([PATHS.login, PATHS.setup, PATHS.password])

export const STUDIO_ROUTE_PATHS = [
  PATHS.generateImage,
  ROUTE_PATTERNS.generateImageJob,
  PATHS.generateVideo,
  ROUTE_PATTERNS.generateVideoJob,
  ROUTE_PATTERNS.directorBatch,
  ROUTE_PATTERNS.directorProject,
  PATHS.director,
  PATHS.assets,
] as const

export type LoginRedirectState = {
  from?: Pick<Location, "pathname" | "search" | "hash">
}

export type StudioWorkspace = "generate" | "director" | "assets"
export type GenerateMediaType = "image" | "video"

export function generateJobPath(mediaType: GenerateMediaType, jobId?: string) {
  const base = mediaType === "image" ? PATHS.generateImage : PATHS.generateVideo
  return jobId ? `${base}/${encodeURIComponent(jobId)}` : base
}

export function studioWorkspaceFromPath(pathname: string): StudioWorkspace {
  if (pathname === PATHS.assets) return "assets"
  if (pathname === PATHS.director || pathname.startsWith(`${PATHS.director}/`)) return "director"
  return "generate"
}

export function parseGeneratePath(pathname: string): { mediaType: GenerateMediaType; jobId?: string } | null {
  const imagePrefix = `${PATHS.generateImage}/`
  const videoPrefix = `${PATHS.generateVideo}/`
  if (pathname === PATHS.generateImage) return { mediaType: "image" }
  if (pathname === PATHS.generateVideo) return { mediaType: "video" }
  if (pathname.startsWith(imagePrefix)) {
    const rest = pathname.slice(imagePrefix.length)
    if (!rest || rest.includes("/")) return { mediaType: "image" }
    return { mediaType: "image", jobId: decodeURIComponent(rest) }
  }
  if (pathname.startsWith(videoPrefix)) {
    const rest = pathname.slice(videoPrefix.length)
    if (!rest || rest.includes("/")) return { mediaType: "video" }
    return { mediaType: "video", jobId: decodeURIComponent(rest) }
  }
  return null
}

export function directorProjectPath(projectId: string) {
  return `${PATHS.director}/${encodeURIComponent(projectId)}`
}

export function directorBatchPath(projectId: string) {
  return `${PATHS.director}/batch/${encodeURIComponent(projectId)}`
}

export function adminTabPath(tab: AdminTab) {
  return `${PATHS.admin}/${tab}`
}

export function isAdminTab(value: string | undefined): value is AdminTab {
  return value === "accounts" || value === "providers" || value === "llm" || value === "storage"
}

export function isAdminPath(pathname: string) {
  return pathname === PATHS.admin || pathname.startsWith(`${PATHS.admin}/`)
}

export function canAccessAdminTab(role: UserRole, tab: string) {
  if (role === "employee") return false
  if (tab === "accounts") return true
  return role === "super_admin" && isAdminTab(tab)
}

export function isAuthScreenPath(pathname: string) {
  return AUTH_SCREEN_PATHS.has(pathname)
}

function isSafeInternalPath(pathname: string) {
  return pathname.startsWith("/") && !pathname.startsWith("//")
}

export function loginRedirectFrom(state: unknown): string {
  const from = (state as LoginRedirectState | null)?.from
  const pathname = from?.pathname
  if (!pathname || !isSafeInternalPath(pathname) || isAuthScreenPath(pathname)) {
    return PATHS.generateVideo
  }
  return `${pathname}${from.search ?? ""}${from.hash ?? ""}`
}

export function locationFromState(location: Pick<Location, "pathname" | "search" | "hash">): LoginRedirectState {
  return { from: { pathname: location.pathname, search: location.search, hash: location.hash } }
}

export function resolveAuthRedirect(
  auth: AuthStatus,
  location: Pick<Location, "pathname" | "search" | "hash" | "state">,
): { to: string; state?: LoginRedirectState } | null {
  const { pathname } = location
  const fromState = locationFromState(location)

  if (auth.setup_required) {
    return pathname === PATHS.setup ? null : { to: PATHS.setup, state: fromState }
  }
  if (!auth.authenticated || !auth.user || !auth.csrf_token) {
    return pathname === PATHS.login ? null : { to: PATHS.login, state: fromState }
  }
  if (auth.user.must_change_password) {
    return pathname === PATHS.password ? null : { to: PATHS.password, state: fromState }
  }
  if (isAuthScreenPath(pathname)) {
    return { to: loginRedirectFrom(location.state) }
  }
  if (isAdminPath(pathname) && auth.user.role === "employee") {
    return { to: PATHS.generateVideo }
  }
  return null
}
