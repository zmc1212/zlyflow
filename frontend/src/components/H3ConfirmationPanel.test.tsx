import { isValidElement, type ReactNode } from "react"
import { Button, Select, Tabs } from "antd"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { H3ConfirmationPanel } from "./H3ConfirmationPanel"
import { requestJson } from "../api"

const hooks = vi.hoisted(() => ({ values: [] as unknown[] }))
vi.mock("react", async () => ({
  ...await vi.importActual<typeof import("react")>("react"),
  useState: (initial: unknown) => [hooks.values.length ? hooks.values.shift() : initial, vi.fn()],
  useEffect: vi.fn(), useCallback: (fn: unknown) => fn, useRef: (current: unknown) => ({ current }),
}))
vi.mock("../api", () => ({
  requestJson: vi.fn(), jsonMutation: (csrf: string, body: unknown) => ({ method: "POST", body: JSON.stringify(body), csrf }),
}))
function nodes(node: ReactNode): Array<{ type: unknown; props: Record<string, any> }> {
  if (Array.isArray(node)) return node.flatMap(nodes)
  if (!isValidElement<Record<string, any>>(node)) return []
  return [{ type: node.type, props: node.props }, ...nodes(node.props.children),
    ...(node.props.items || []).flatMap((item: {children?: ReactNode}) => nodes(item.children))]
}
const source = { eligible: true, source_job_id: "first", source_revision: "frozen-v1", source_url: "/first.mp4", children: [] }
function render(state: Record<string, unknown>, extra = {}) {
  hooks.values = [state, 2, false, "", undefined, ""]
  return nodes(H3ConfirmationPanel({ endpoint: "/api/jobs/first/refine", csrfToken: "csrf", ...extra }))
}

describe("H3 explicit confirmation", () => {
  beforeEach(() => vi.clearAllMocks())
  it("does not submit on display; confirms only quality and frozen source", async () => {
    const tree = render(source)
    expect(requestJson).not.toHaveBeenCalled()
    vi.mocked(requestJson).mockResolvedValueOnce({ id: "second" }).mockResolvedValueOnce(source)
    const button = tree.find(n => n.type === Button && n.props.children === "确认并生成二采")!
    await button.props.onClick()
    const [url, init] = vi.mocked(requestJson).mock.calls[0]
    expect(url).toBe("/api/jobs/first/refine")
    expect(JSON.parse(String(init?.body))).toEqual({refine_quality:2,source_revision:"frozen-v1",request_id:expect.any(String)})
    expect(tree.some(n => n.type === Select && n.props["aria-label"] === "二采目标画质")).toBe(true)
  })
  it("blocks duplicate confirmation while preserving first-pass video", () => {
    const tree = render({...source, children:[{id:"second",status:"running",progress:20,quality:1}]})
    expect(tree.find(n => n.type === Button && n.props.children === "确认并生成二采")?.props.disabled).toBe(true)
    expect(tree.find(n => n.type === Select)?.props.value).toBe(1)
    expect(tree.some(n => n.props.children === "已确认 · 二采进行中")).toBe(true)
    expect(tree.some(n => n.type === "video" && n.props.src === "/first.mp4")).toBe(true)
    expect(tree.some(n => n.type === Button && n.props.children === "取消二采")).toBe(true)
  })
  it("defaults to completed refine but keeps source tab and read-only protection", () => {
    const tree = render({...source, children:[{id:"second",status:"completed",url:"/second.mp4",quality:1}]}, {readOnly:true})
    const tabs = tree.find(n => n.type === Tabs)!
    expect(tabs.props.activeKey).toBe("second")
    expect(tabs.props.items.map((item: {key:string}) => item.key)).toEqual(["source","second"])
    expect(tree.some(n => n.type === Button && n.props.children === "确认并生成二采")).toBe(false)
  })
  it("offers explicit new preview after cache loss and blocks a silent resample", () => {
    const tree = render({...source, children:[{id:"second",status:"failed",error:"FIRST_PASS_CACHE_INVALID"}]})
    expect(tree.find(n => n.type === Button && n.props.children === "确认并生成二采")?.props.disabled).toBe(true)
    // Ant Design Alert owns its action; inspect that prop rather than mounting a synthetic DOM.
    expect(tree.some(n => isValidElement<{children?: ReactNode}>(n.props.action)
      && n.props.action.props.children === "重新生成一采预览")).toBe(true)
  })
  it("uses authorized local media after temporary download links expire", () => {
    const tree = render({...source, source_url:null, source_path:"first.mp4",
      children:[{id:"second",status:"completed",output_path:"second.mp4",quality:1}]},
      {localUrls:{"first.mp4":"blob:first","second.mp4":"blob:second"}})
    expect(tree.filter(n => n.type === "video").map(n => n.props.src)).toEqual(["blob:first","blob:second"])
  })
})
