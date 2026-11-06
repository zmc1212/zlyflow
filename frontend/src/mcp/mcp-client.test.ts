import { describe, expect, it } from "vitest"
import { connectionConfig } from "./mcp-client"
import { loginRedirectFrom, PATHS, resolveAuthRedirect } from "../paths"

describe("MCP client configuration", () => {
  it("uses the configured URL and OAuth login without embedding credentials", () => {
    const url = "https://studio.example.com/api/mcp"
    expect(connectionConfig("codex", url)).toContain('codex mcp login zly-ai-studio')
    const expected = { mcpServers: { "zly-ai-studio": { type: "http", url } } }
    for (const client of ["cursor", "chatgpt", "claude"] as const) expect(JSON.parse(connectionConfig(client, url))).toEqual(expected)
    expect(connectionConfig("generic", url)).toContain("mcpServers")
    expect(connectionConfig("generic", url)).toContain("OAuth 2.1")
  })
  it("restores the OAuth request after the existing login redirect", () => {
    const from = { pathname: PATHS.mcpAuthorize, search: "?request_id=opaque-request", hash: "" }
    expect(loginRedirectFrom({ from })).toBe("/mcp/authorize?request_id=opaque-request")
    const redirected = resolveAuthRedirect({ setup_required: false, authenticated: false }, { ...from, state: null })
    expect(redirected?.to).toBe(PATHS.login)
    expect(redirected?.state).toEqual({ from })
  })
})
