import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Navigate, useLocation } from "react-router-dom"
import { AuthStatus, jsonMutation, requestJson } from "./api"
import { CenteredStatus } from "./auth/AuthScreens"
import { PATHS, resolveAuthRedirect } from "./paths"
import { AppRoutes } from "./router"

export default function Root() {
  const queryClient = useQueryClient()
  const location = useLocation()
  const authQuery = useQuery({
    queryKey: ["auth"],
    queryFn: () => requestJson<AuthStatus>("/api/auth/status"),
    retry: false,
  })

  const logoutMutation = useMutation({
    mutationFn: () => requestJson<{ ok: boolean }>("/api/auth/logout", jsonMutation(authQuery.data?.csrf_token ?? "")),
    onSuccess: () => {
      queryClient.clear()
      window.location.assign(PATHS.login)
    },
  })

  if (authQuery.isLoading) return <CenteredStatus label="正在连接工作台" />
  if (authQuery.isError) return <CenteredStatus label="工作台连接失败" detail={authQuery.error.message} />
  const auth = authQuery.data
  if (!auth) return <CenteredStatus label="工作台未返回登录状态" />

  const redirect = resolveAuthRedirect(auth, location)
  if (redirect) return <Navigate to={redirect.to} replace state={redirect.state} />

  return <AppRoutes
    auth={auth}
    onAuthenticated={(nextAuth) => queryClient.setQueryData(["auth"], nextAuth)}
    onLogout={() => logoutMutation.mutate()}
    logoutPending={logoutMutation.isPending}
  />
}
