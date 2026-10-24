import { describe, expect, it } from "vitest"
import { connectionConfig, moveReference, referenceInstruction } from "./mcp-client"
import { loginRedirectFrom, PATHS, resolveAuthRedirect } from "../paths"

describe("MCP client configuration and ordered references", () => {
  it("uses the configured URL and OAuth login without embedding credentials", () => {
    const url = "https://studio.example.com/api/mcp"
    expect(connectionConfig("codex", url)).toContain('codex mcp login zly-ai-studio')
    expect(JSON.parse(connectionConfig("cursor", url))).toEqual({ mcpServers: { "zly-ai-studio": { url } } })
    expect(connectionConfig("generic", url)).toContain("OAuth 2.1")
  })
  it("preserves the user's reference order and Picture numbering", () => {
    const ids = ["first", "second", "third"]
    const reordered = moveReference(ids, 1, -1)
    expect(ids).toEqual(["first", "second", "third"])
    expect(referenceInstruction(reordered.map((id) => ({ id })))).toBe("<Picture 1>：second\n<Picture 2>：first\n<Picture 3>：third")
    expect(moveReference(ids, 0, -1)).toEqual(ids)
  })
  it("restores the OAuth request after the existing login redirect", () => {
    const from = { pathname: PATHS.mcpAuthorize, search: "?request_id=opaque-request", hash: "" }
    expect(loginRedirectFrom({ from })).toBe("/mcp/authorize?request_id=opaque-request")
    const redirected = resolveAuthRedirect({ setup_required: false, authenticated: false }, { ...from, state: null })
    expect(redirected?.to).toBe(PATHS.login)
    expect(redirected?.state).toEqual({ from })
  })
})
