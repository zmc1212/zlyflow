/**
 * Host half of the ZLY AI Video Studio bundle.
 *
 * The studio's MCP endpoint only speaks OAuth 2.1 (authorization code + PKCE,
 * 1-hour access tokens). DSH's MCP client accepts static headers only, so this
 * plugin owns the OAuth client:
 *
 *   1. opens the studio consent page in the system browser (loopback callback),
 *   2. exchanges the code and keeps the refresh token in DSH credentials,
 *   3. rotates the access token before it expires,
 *   4. registers the studio MCP server with a `${credential:...}` bearer header,
 *      so mcp-client rebuilds its connection whenever the token rotates.
 *
 * The panel talks to the three loopback routes below to show status and start
 * or refresh the connection.
 */
import { createHash, randomBytes } from 'node:crypto'

const DEFAULT_STUDIO_URL = 'https://comfyui.zlyun168.com'
const SERVER_NAME = 'zlystudio'
const TOKEN_REF = 'ZLY_STUDIO_MCP_TOKEN'
const SESSION_REF = 'ZLY_STUDIO_MCP_SESSION'
const CALLBACK_PATH = '/zly-studio/mcp/callback'
const STATUS_PATH = '/zly-studio/mcp/status'
const START_PATH = '/zly-studio/mcp/start'
const REFRESH_PATH = '/zly-studio/mcp/refresh'
const LOGIN_PATH = '/zly-studio/mcp/login'
const DISCONNECT_PATH = '/zly-studio/mcp/disconnect'
const PENDING_TTL_MS = 10 * 60 * 1000
const REFRESH_AHEAD_MS = 60 * 1000

export const inject = ['mcpManager', 'credentials', 'webServer']

/** @param {Buffer|string} value */
function base64url(value) {
  return Buffer.from(value).toString('base64url')
}

function normalizeOrigin(value) {
  return String(value || '').trim().replace(/\/+$/, '')
}

function loopbackOrigin(origin) {
  try {
    const parsed = new URL(origin)
    if (parsed.hostname === '127.0.0.1' || parsed.hostname === 'localhost' || parsed.hostname === '::1') {
      return parsed.origin
    }
    return `http://127.0.0.1:${parsed.port || '80'}`
  } catch {
    return origin
  }
}

function isLoopbackRequest(req) {
  const address = req.socket?.remoteAddress || ''
  return address === '127.0.0.1' || address === '::1' || address === '::ffff:127.0.0.1'
}

function sendJson(res, status, body) {
  res.statusCode = status
  res.setHeader('content-type', 'application/json; charset=utf-8')
  res.setHeader('cache-control', 'no-store')
  res.end(JSON.stringify(body))
}

function sendHtml(res, status, body) {
  res.statusCode = status
  res.setHeader('content-type', 'text/html; charset=utf-8')
  res.setHeader('cache-control', 'no-store')
  res.end(`<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>ZLY 视频工作台</title><body style="font:14px/1.6 system-ui,sans-serif;padding:32px;color:#171a1f;background:#f8f9fa">${body}</body></html>`)
}

/**
 * @param {import('@deepseek-ai/cordis').Context} ctx
 * @param {{ studioUrl?: string, scopes?: string }} [config]
 */
export function apply(ctx, config = {}) {
  const studioUrl = normalizeOrigin(config.studioUrl) || DEFAULT_STUDIO_URL
  const scopes = typeof config.scopes === 'string' && config.scopes.trim()
    ? config.scopes.trim()
    : 'studio:read studio:generate studio:edit'
  const resource = `${studioUrl}/api/mcp`
  const issuer = `${studioUrl}/api/mcp/oauth`

  /** @type {{ clientId: string, redirectUri: string, accessToken: string, refreshToken: string, expiresAt: number, scope: string } | null} */
  let session = null
  /** @type {{ state: string, verifier: string, redirectUri: string, clientId: string, at: number } | null} */
  let pending = null
  let mcpDisposer = null
  let refreshTimer = null
  let lastError = ''

  const log = (message) => {
    try {
      ctx.logger?.('zly-studio')?.warn?.(message)
    } catch {
      // Logging is best-effort; the panel shows the same state.
    }
  }

  async function readSession() {
    try {
      const stored = await ctx.credentials.resolve(SESSION_REF)
      if (!stored?.value) return null
      const parsed = JSON.parse(stored.value)
      return parsed && typeof parsed === 'object' ? parsed : null
    } catch (error) {
      log(`读取 MCP 会话失败: ${error instanceof Error ? error.message : String(error)}`)
      return null
    }
  }

  async function persistSession(next) {
    session = next
    await ctx.credentials.set(SESSION_REF, JSON.stringify(next))
    await ctx.credentials.set(TOKEN_REF, next.accessToken)
  }

  function registerServer() {
    if (mcpDisposer) return
    try {
      mcpDisposer = ctx.mcpManager.register(SERVER_NAME, {
        transport: 'streamable-http',
        url: resource,
        headers: { Authorization: `Bearer \${credential:${TOKEN_REF}}` },
        expandTemplates: true,
        toolCallTimeoutMs: 120000,
      })
    } catch (error) {
      lastError = `注册 MCP 服务失败: ${error instanceof Error ? error.message : String(error)}`
      log(lastError)
    }
  }

  function scheduleRefresh() {
    if (refreshTimer) clearTimeout(refreshTimer)
    refreshTimer = null
    if (!session?.expiresAt) return
    const delay = Math.max(30_000, session.expiresAt - Date.now() - REFRESH_AHEAD_MS)
    refreshTimer = setTimeout(() => {
      refreshAccess().catch((error) => {
        lastError = `刷新令牌失败: ${error instanceof Error ? error.message : String(error)}`
        log(lastError)
      })
    }, delay)
    refreshTimer.unref?.()
  }

  async function refreshAccess() {
    if (!session?.refreshToken) throw new Error('没有可用的刷新令牌，请重新连接')
    const body = new URLSearchParams({
      grant_type: 'refresh_token',
      refresh_token: session.refreshToken,
      client_id: session.clientId,
      resource,
    })
    const response = await fetch(`${issuer}/token`, {
      method: 'POST',
      headers: { 'content-type': 'application/x-www-form-urlencoded' },
      body,
    })
    if (!response.ok) {
      throw new Error(`HTTP ${response.status} ${(await response.text()).slice(0, 200)}`)
    }
    const data = await response.json()
    const next = {
      ...session,
      accessToken: data.access_token,
      refreshToken: data.refresh_token || session.refreshToken,
      expiresAt: Date.now() + Number(data.expires_in || 3600) * 1000,
      scope: data.scope || session.scope,
    }
    await persistSession(next)
    lastError = ''
    registerServer()
    scheduleRefresh()
    return next
  }

  async function registerClient(redirectUri) {
    const response = await fetch(`${issuer}/register`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        client_name: 'DeepSeek Harness · ZLY Studio',
        redirect_uris: [redirectUri],
        grant_types: ['authorization_code', 'refresh_token'],
        response_types: ['code'],
        token_endpoint_auth_method: 'none',
      }),
    })
    if (!response.ok) {
      throw new Error(`注册客户端失败: HTTP ${response.status} ${(await response.text()).slice(0, 200)}`)
    }
    const data = await response.json()
    if (!data.client_id) throw new Error('注册客户端失败: 响应缺少 client_id')
    return data.client_id
  }

  async function startAuth() {
    const origin = loopbackOrigin(ctx.webServer.getOrigin())
    const redirectUri = origin + CALLBACK_PATH
    const verifier = base64url(randomBytes(48))
    const challenge = base64url(createHash('sha256').update(verifier).digest())
    const state = base64url(randomBytes(24))
    const clientId = await registerClient(redirectUri)
    pending = { state, verifier, redirectUri, clientId, at: Date.now() }
    const params = new URLSearchParams({
      response_type: 'code',
      client_id: clientId,
      redirect_uri: redirectUri,
      scope: scopes,
      state,
      code_challenge: challenge,
      code_challenge_method: 'S256',
      resource,
    })
    return `${issuer}/authorize?${params.toString()}`
  }

  async function autoConnect(username, password) {
    const loginResponse = await fetch(`${studioUrl}/api/auth/login`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ username, password }),
    })
    if (!loginResponse.ok) {
      const detail = (await loginResponse.text()).slice(0, 160)
      throw new Error(loginResponse.status === 401 ? '账号或密码不正确' : `登录失败: HTTP ${loginResponse.status} ${detail}`)
    }
    const login = await loginResponse.json()
    const csrf = login?.csrf_token
    if (!csrf) throw new Error('登录响应缺少 CSRF 令牌')
    const cookieHeader = (loginResponse.headers.getSetCookie?.() || [])
      .map((value) => value.split(';')[0])
      .join('; ')

    const redirectUri = 'http://127.0.0.1:18765/zly-studio/mcp/auto'
    const clientId = await registerClient(redirectUri)
    const verifier = base64url(randomBytes(48))
    const challenge = base64url(createHash('sha256').update(verifier).digest())
    const state = base64url(randomBytes(24))
    const params = new URLSearchParams({
      response_type: 'code',
      client_id: clientId,
      redirect_uri: redirectUri,
      scope: scopes,
      state,
      code_challenge: challenge,
      code_challenge_method: 'S256',
      resource,
    })
    const authorizeResponse = await fetch(`${issuer}/authorize?${params.toString()}`, {
      redirect: 'manual',
      headers: cookieHeader ? { cookie: cookieHeader } : undefined,
    })
    const location = authorizeResponse.headers.get('location') || ''
    const requestId = /[?&]request_id=([^&]+)/.exec(location)?.[1]
    if (!requestId) throw new Error(`发起授权失败: HTTP ${authorizeResponse.status}`)

    const decisionResponse = await fetch(`${studioUrl}/api/mcp/authorization-requests/${encodeURIComponent(requestId)}`, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'X-CSRF-Token': csrf,
        ...(cookieHeader ? { cookie: cookieHeader } : {}),
      },
      body: JSON.stringify({ allow: true }),
    })
    if (!decisionResponse.ok) {
      throw new Error(`授权失败: HTTP ${decisionResponse.status} ${(await decisionResponse.text()).slice(0, 160)}`)
    }
    const decision = await decisionResponse.json()
    const code = new URL(decision.redirect_url).searchParams.get('code')
    if (!code) throw new Error('授权响应缺少 code')

    const tokenResponse = await fetch(`${issuer}/token`, {
      method: 'POST',
      headers: { 'content-type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        grant_type: 'authorization_code',
        code,
        redirect_uri: redirectUri,
        client_id: clientId,
        code_verifier: verifier,
        resource,
      }),
    })
    if (!tokenResponse.ok) {
      throw new Error(`换取令牌失败: HTTP ${tokenResponse.status} ${(await tokenResponse.text()).slice(0, 160)}`)
    }
    const data = await tokenResponse.json()
    const next = {
      clientId,
      redirectUri,
      accessToken: data.access_token,
      refreshToken: data.refresh_token,
      expiresAt: Date.now() + Number(data.expires_in || 3600) * 1000,
      scope: data.scope || scopes,
    }
    await persistSession(next)
    lastError = ''
    registerServer()
    scheduleRefresh()
    return next
  }

  async function completeAuth(code, state) {
    if (!pending || pending.state !== state || Date.now() - pending.at > PENDING_TTL_MS) {
      throw new Error('授权请求已过期，请重新发起连接')
    }
    const body = new URLSearchParams({
      grant_type: 'authorization_code',
      code,
      redirect_uri: pending.redirectUri,
      client_id: pending.clientId,
      code_verifier: pending.verifier,
      resource,
    })
    const response = await fetch(`${issuer}/token`, {
      method: 'POST',
      headers: { 'content-type': 'application/x-www-form-urlencoded' },
      body,
    })
    if (!response.ok) {
      throw new Error(`换取令牌失败: HTTP ${response.status} ${(await response.text()).slice(0, 200)}`)
    }
    const data = await response.json()
    const next = {
      clientId: pending.clientId,
      redirectUri: pending.redirectUri,
      accessToken: data.access_token,
      refreshToken: data.refresh_token,
      expiresAt: Date.now() + Number(data.expires_in || 3600) * 1000,
      scope: data.scope || scopes,
    }
    pending = null
    await persistSession(next)
    lastError = ''
    registerServer()
    scheduleRefresh()
    return next
  }

  function serverStatus() {
    try {
      const row = ctx.mcpManager.list().find((item) => item.name === SERVER_NAME)
      return row ? row.status : null
    } catch {
      return null
    }
  }

  function publicStatus() {
    return {
      connected: Boolean(session?.accessToken),
      expiresAt: session?.expiresAt ?? null,
      studioUrl,
      resource,
      scopes: session?.scope ?? scopes,
      lastError,
      server: serverStatus(),
    }
  }

  function guard(req, res) {
    if (!isLoopbackRequest(req)) {
      sendJson(res, 403, { error: '仅允许本机访问' })
      return false
    }
    return true
  }

  ctx.effect(() => {
    let disposed = false
    ;(async () => {
      session = await readSession()
      if (disposed || !session?.refreshToken) return
      try {
        if (!session.expiresAt || session.expiresAt < Date.now() + REFRESH_AHEAD_MS) {
          await refreshAccess()
        } else {
          registerServer()
          scheduleRefresh()
        }
      } catch (error) {
        lastError = error instanceof Error ? error.message : String(error)
        log(lastError)
      }
    })()
    return () => {
      disposed = true
      if (refreshTimer) clearTimeout(refreshTimer)
      refreshTimer = null
      mcpDisposer?.()
      mcpDisposer = null
    }
  }, 'zly-studio: MCP session')

  ctx.effect(() => ctx.webServer.register({
    kind: 'exact',
    path: STATUS_PATH,
    handler: async (req, res) => {
      if (!guard(req, res)) return
      if (req.method !== 'GET') return sendJson(res, 405, { error: 'method not allowed' })
      sendJson(res, 200, publicStatus())
    },
  }), `zly-studio: GET ${STATUS_PATH}`)

  ctx.effect(() => ctx.webServer.register({
    kind: 'exact',
    path: START_PATH,
    handler: async (req, res) => {
      if (!guard(req, res)) return
      if (req.method !== 'POST') return sendJson(res, 405, { error: 'method not allowed' })
      try {
        const url = await startAuth()
        sendJson(res, 200, { url })
      } catch (error) {
        lastError = error instanceof Error ? error.message : String(error)
        sendJson(res, 500, { error: lastError })
      }
    },
  }), `zly-studio: POST ${START_PATH}`)

  ctx.effect(() => ctx.webServer.register({
    kind: 'exact',
    path: LOGIN_PATH,
    handler: async (req, res) => {
      if (!guard(req, res)) return
      if (req.method !== 'POST') return sendJson(res, 405, { error: 'method not allowed' })
      let raw = ''
      for await (const chunk of req) {
        raw += chunk
        if (raw.length > 8192) return sendJson(res, 413, { error: '请求过大' })
      }
      try {
        const body = JSON.parse(raw || '{}')
        const username = String(body.username || '').trim()
        const password = String(body.password || '')
        if (!username || !password) throw new Error('请输入工作台账号和密码')
        await autoConnect(username, password)
        sendJson(res, 200, publicStatus())
      } catch (error) {
        lastError = error instanceof Error ? error.message : String(error)
        sendJson(res, 400, { error: lastError })
      }
    },
  }), `zly-studio: POST ${LOGIN_PATH}`)

  ctx.effect(() => ctx.webServer.register({
    kind: 'exact',
    path: REFRESH_PATH,
    handler: async (req, res) => {
      if (!guard(req, res)) return
      if (req.method !== 'POST') return sendJson(res, 405, { error: 'method not allowed' })
      try {
        await refreshAccess()
        sendJson(res, 200, publicStatus())
      } catch (error) {
        lastError = error instanceof Error ? error.message : String(error)
        sendJson(res, 500, { error: lastError })
      }
    },
  }), `zly-studio: POST ${REFRESH_PATH}`)

  ctx.effect(() => ctx.webServer.register({
    kind: 'exact',
    path: DISCONNECT_PATH,
    handler: async (req, res) => {
      if (!guard(req, res)) return
      if (req.method !== 'POST') return sendJson(res, 405, { error: 'method not allowed' })
      if (refreshTimer) clearTimeout(refreshTimer)
      refreshTimer = null
      session = null
      pending = null
      try {
        await ctx.credentials.unset(SESSION_REF)
      } catch {}
      try {
        await ctx.credentials.unset(TOKEN_REF)
      } catch {}
      mcpDisposer?.()
      mcpDisposer = null
      lastError = ''
      sendJson(res, 200, publicStatus())
    },
  }), `zly-studio: POST ${DISCONNECT_PATH}`)

  ctx.effect(() => ctx.webServer.register({
    kind: 'exact',
    path: CALLBACK_PATH,
    handler: async (req, res) => {
      if (!guard(req, res)) return
      if (req.method !== 'GET') return sendHtml(res, 405, '不支持的方法')
      const url = new URL(req.url, 'http://localhost')
      const error = url.searchParams.get('error')
      if (error) return sendHtml(res, 400, `授权未完成：${error}。可以关闭此页并回到 DSH 重试。`)
      const code = url.searchParams.get('code')
      const state = url.searchParams.get('state')
      if (!code || !state) return sendHtml(res, 400, '回调缺少参数，请回到 DSH 重新连接。')
      try {
        await completeAuth(code, state)
        return sendHtml(res, 200, '已连接 ZLY 视频工作台，MCP 工具会在几秒内出现在 DSH 中。可以关闭此页。')
      } catch (failure) {
        lastError = failure instanceof Error ? failure.message : String(failure)
        return sendHtml(res, 500, `连接失败：${lastError}。请回到 DSH 重试。`)
      }
    },
  }), `zly-studio: GET ${CALLBACK_PATH}`)

}