import type { Location } from "react-router-dom"
import type { AuthStatus, UserRole } from "./api"

// Motion transfer has a dedicated tool page under the tools workspace; keep it registered here.
export const PATHS = {
  home: "/",
  login: "/login",
  setup: "/setup",
  password: "/password",
  mcp: "/mcp",
  mcpAuthorize: "/mcp/authorize",
  generateImage: "/generate/image",
  generateVideo: "/generate/video",
  tools: "/tools",
  inspiration: "/inspiration",
  music: "/music",
  toolPromptReverse: "/tools/prompt-reverse",
  toolMotionTransfer: "/tools/motion-transfer",
  toolCharacterReplace: "/tools/character-replace",
  toolFaceSwap: "/tools/face-swap",
  toolPartialRetake: "/tools/partial-retake",
  toolKeyframeNarrative: "/tools/keyframe-narrative",
  toolActionShot: "/tools/action-shot",
  toolDepthCapture: "/tools/depth-capture",
  toolVideoEdit: "/tools/video-edit",
  toolVideoUpscale: "/tools/video-upscale",
  toolFaceRestore: "/tools/face-restore",
  toolStemSplit: "/tools/stem-split",
  toolDigitalHuman: "/tools/digital-human",
  toolLipSync: "/tools/lip-sync",
  toolImageBgRemove: "/tools/image-bg-remove",
  toolImageBgRemoveEditor: "/tools/image-bg-remove/editor",
  toolImageLayerSplit: "/tools/image-layer-split",
  toolPhotoEdit: "/tools/photo-edit",
  toolImageInpaint: "/tools/image-inpaint",
  toolImageEraser: "/tools/image-eraser",
  toolImageOutpaint: "/tools/image-outpaint",
  director: "/director",
  director2: "/director2",
  canvas: "/canvas",
  assets: "/assets",
  admin: "/admin",
  adminAccounts: "/admin/accounts",
  adminProviders: "/admin/providers",
  adminLlm: "/admin/llm",
  adminVlm: "/admin/vlm",
  adminTts: "/admin/tts",
  adminStorage: "/admin/storage",
  adminMail: "/admin/mail",
} as const

export const ROUTE_PATTERNS = {
  generateImageJob: "/generate/image/:jobId",
  generateVideoJob: "/generate/video/:jobId",
  musicChat: "/music/:chatId",
  directorLegacyRecipe: "/director/:projectId",
  directorDiagnosis: "/director/script-diagnosis",
  directorBatch: "/director/batch/:projectId",
  directorReplication: "/director/replication/:projectId",
  directorProject: "/director/projects/:projectId",
  directorProjectMenu: "/director/projects/:projectId/:menu",
  directorProjectEpisode: "/director/projects/:projectId/workshop/:episodeId",
  directorProjectEdit: "/director/projects/:projectId/edit/:episodeId",
  directorProjectWorkbench: "/director/projects/:projectId/workbench/:episodeId",
  directorFeatured: "/director/featured/:featuredId",
  directorFeaturedProcess: "/director/featured/:featuredId/process",
  director2: "/director2",
  director2Splat: "/director2/*",
  canvasProject: "/canvas/:canvasId",
  director2Project: "/director2/projects/:projectId",
  director2ProjectMenu: "/director2/projects/:projectId/:menu",
  director2ProjectEpisode: "/director2/projects/:projectId/workshop/:episodeId",
  adminTab: "/admin/:tab",
} as const

export const ADMIN_TABS = ["accounts", "providers", "llm", "vlm", "tts", "storage", "mail"] as const
export type AdminTab = (typeof ADMIN_TABS)[number]
export const SUPER_ADMIN_ONLY_TABS: readonly AdminTab[] = ["providers", "llm", "vlm", "tts", "storage", "mail"]

const AUTH_SCREEN_PATHS = new Set<string>([PATHS.login, PATHS.setup, PATHS.password])

export const STUDIO_ROUTE_PATHS = [
  ROUTE_PATTERNS.directorDiagnosis,
  PATHS.generateImage,
  ROUTE_PATTERNS.generateImageJob,
  PATHS.generateVideo,
  ROUTE_PATTERNS.generateVideoJob,
  PATHS.tools,
  PATHS.inspiration,
  PATHS.music,
  ROUTE_PATTERNS.musicChat,
  PATHS.toolPromptReverse,
  PATHS.toolMotionTransfer,
  PATHS.toolCharacterReplace,
  PATHS.toolFaceSwap,
  PATHS.toolPartialRetake,
  PATHS.toolKeyframeNarrative,
  PATHS.toolActionShot,
  PATHS.toolDepthCapture,
  PATHS.toolVideoEdit,
  PATHS.toolVideoUpscale,
  PATHS.toolFaceRestore,
  PATHS.toolStemSplit,
  PATHS.toolDigitalHuman,
  PATHS.toolLipSync,
  PATHS.toolImageBgRemove,
  PATHS.toolImageBgRemoveEditor,
  PATHS.toolImageLayerSplit,
  PATHS.toolPhotoEdit,
  PATHS.toolImageInpaint,
  PATHS.toolImageEraser,
  PATHS.toolImageOutpaint,
  ROUTE_PATTERNS.directorBatch,
  ROUTE_PATTERNS.directorReplication,
  ROUTE_PATTERNS.directorProject,
  ROUTE_PATTERNS.directorProjectMenu,
  ROUTE_PATTERNS.directorProjectEpisode,
  ROUTE_PATTERNS.directorProjectEdit,
  ROUTE_PATTERNS.directorProjectWorkbench,
  ROUTE_PATTERNS.directorFeatured,
  ROUTE_PATTERNS.directorFeaturedProcess,
  PATHS.director,
  PATHS.canvas,
  ROUTE_PATTERNS.canvasProject,
  PATHS.assets,
] as const

export const DIRECTOR2_REDIRECT_ROUTE_PATHS = [
  ROUTE_PATTERNS.director2,
  ROUTE_PATTERNS.director2Project,
  ROUTE_PATTERNS.director2ProjectMenu,
  ROUTE_PATTERNS.director2ProjectEpisode,
  ROUTE_PATTERNS.director2Splat,
] as const

export type LoginRedirectState = {
  from?: Pick<Location, "pathname" | "search" | "hash">
}

export type StudioWorkspace = "generate" | "inspiration" | "music" | "tools" | "director" | "canvas" | "assets"
export type GenerateMediaType = "image" | "video"

const DIRECTOR_LEGACY_STUDIO_SEGMENTS = new Set(["batch", "replication"])

export function generateJobPath(mediaType: GenerateMediaType, jobId?: string) {
  const base = mediaType === "image" ? PATHS.generateImage : PATHS.generateVideo
  return jobId ? `${base}/${encodeURIComponent(jobId)}` : base
}

export function musicChatPath(chatId?: string | null) {
  return chatId ? `${PATHS.music}/${encodeURIComponent(chatId)}` : PATHS.music
}

export function parseMusicPath(pathname: string): { chatId?: string } {
  const prefix = `${PATHS.music}/`
  if (!pathname.startsWith(prefix)) return {}
  const rest = pathname.slice(prefix.length)
  if (!rest || rest.includes("/")) return {}
  return { chatId: decodeURIComponent(rest) }
}

export function studioWorkspaceFromPath(pathname: string): StudioWorkspace {
  if (pathname === PATHS.assets) return "assets"
  if (pathname === PATHS.inspiration) return "inspiration"
  if (pathname === PATHS.music || pathname.startsWith(`${PATHS.music}/`)) return "music"
  if (pathname === PATHS.tools || pathname.startsWith(`${PATHS.tools}/`)) return "tools"
  if (pathname === PATHS.canvas || pathname.startsWith(`${PATHS.canvas}/`)) return "canvas"
  if (pathname === PATHS.director || pathname.startsWith(`${PATHS.director}/`)) return "director"
  if (pathname === PATHS.director2 || pathname.startsWith(`${PATHS.director2}/`)) return "director"
  return "generate"
}

export function isDirectorLegacyStudioPath(pathname: string): boolean {
  const prefix = `${PATHS.director}/`
  if (!pathname.startsWith(prefix)) return false
  const segment = pathname.slice(prefix.length).split("/")[0]
  return DIRECTOR_LEGACY_STUDIO_SEGMENTS.has(segment)
}

export function director2RedirectTarget(location: Pick<Location, "pathname" | "search" | "hash">): string {
  const { pathname, search = "", hash = "" } = location
  if (pathname === PATHS.director2) return `${PATHS.director}${search}${hash}`
  if (pathname.startsWith(`${PATHS.director2}/`)) {
    return `${PATHS.director}${pathname.slice(PATHS.director2.length)}${search}${hash}`
  }
  return `${PATHS.director}${search}${hash}`
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

export function canvasProjectPath(canvasId: string) {
  return `${PATHS.canvas}/${encodeURIComponent(canvasId)}`
}

export function directorProjectPath(projectId: string) {
  return `${PATHS.director}/${encodeURIComponent(projectId)}`
}

export function directorBatchPath(projectId: string) {
  return `${PATHS.director}/batch/${encodeURIComponent(projectId)}`
}

export function directorReplicationPath(projectId: string) {
  return `${PATHS.director}/replication/${encodeURIComponent(projectId)}`
}

export function adminTabPath(tab: AdminTab) {
  return `${PATHS.admin}/${tab}`
}

export function isAdminTab(value: string | undefined): value is AdminTab {
  return value === "accounts" || value === "providers" || value === "llm" || value === "vlm" || value === "tts" || value === "storage" || value === "mail"
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

export function isGuestStudioPath(pathname: string) {
  return pathname === PATHS.home || pathname === PATHS.login
    || pathname === PATHS.generateImage || pathname === PATHS.generateVideo
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
    return isGuestStudioPath(pathname) ? null : { to: PATHS.login, state: fromState }
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
