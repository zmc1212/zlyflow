import { lazy, Suspense } from "react"
import { Navigate, Route, Routes, useNavigate } from "react-router-dom"
import AdminSettings from "./admin/AdminSettings"
import type { AuthStatus } from "./api"
import { CenteredStatus, CredentialScreen, PasswordChangeScreen } from "./auth/AuthScreens"
import { PATHS, ROUTE_PATTERNS, STUDIO_ROUTE_PATHS } from "./paths"

const App = lazy(() => import("./App"))

export { PATHS, ROUTE_PATTERNS, STUDIO_ROUTE_PATHS } from "./paths"
export {
  ADMIN_TABS,
  SUPER_ADMIN_ONLY_TABS,
  adminTabPath,
  canAccessAdminTab,
  directorBatchPath,
  directorProjectPath,
  generateJobPath,
  isAdminPath,
  isAdminTab,
  isAuthScreenPath,
  loginRedirectFrom,
  locationFromState,
  parseGeneratePath,
  resolveAuthRedirect,
  studioWorkspaceFromPath,
} from "./paths"
export type { AdminTab, GenerateMediaType, LoginRedirectState, StudioWorkspace } from "./paths"

export function AppRoutes({
  auth,
  onAuthenticated,
  onLogout,
  logoutPending,
}: {
  auth: AuthStatus
  onAuthenticated: (nextAuth: AuthStatus) => void
  onLogout: () => void
  logoutPending: boolean
}) {
  const navigate = useNavigate()
  const studioSession = auth.authenticated && auth.user && auth.csrf_token && !auth.setup_required && !auth.user.must_change_password
    ? { user: auth.user, csrfToken: auth.csrf_token }
    : null

  return (
    <Routes>
      <Route path={PATHS.login} element={<CredentialScreen onAuthenticated={onAuthenticated} />} />
      <Route path={PATHS.setup} element={<CredentialScreen setup onAuthenticated={onAuthenticated} />} />
      <Route
        path={PATHS.password}
        element={
          auth.user && auth.csrf_token ? (
            <PasswordChangeScreen
              auth={auth}
              onChanged={onAuthenticated}
              onLogout={onLogout}
              logoutPending={logoutPending}
            />
          ) : (
            <Navigate to={PATHS.login} replace />
          )
        }
      />
      <Route path={PATHS.admin} element={<Navigate to={PATHS.adminAccounts} replace />} />
      <Route
        path={ROUTE_PATTERNS.adminTab}
        element={
          auth.user && auth.csrf_token ? (
            <AdminSettings user={auth.user} csrfToken={auth.csrf_token} />
          ) : (
            <Navigate to={PATHS.login} replace />
          )
        }
      />
      <Route path={PATHS.home} element={<Navigate to={PATHS.generateVideo} replace />} />
      <Route
        element={
          studioSession ? (
            <Suspense fallback={<CenteredStatus label="正在加载创作工作台" />}>
              <App
                user={studioSession.user}
                csrfToken={studioSession.csrfToken}
                onOpenAdmin={studioSession.user.role === "employee" ? undefined : () => navigate(PATHS.adminAccounts)}
                onLogout={onLogout}
                logoutPending={logoutPending}
              />
            </Suspense>
          ) : (
            <Navigate to={PATHS.login} replace />
          )
        }
      >
        {STUDIO_ROUTE_PATHS.map((path) => (
          <Route key={path} path={path} />
        ))}
      </Route>
      <Route path="*" element={<Navigate to={PATHS.generateVideo} replace />} />
    </Routes>
  )
}
