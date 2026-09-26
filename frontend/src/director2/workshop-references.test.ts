import { expect, it } from "vitest"
import { summarizeWorkshopBlocks } from "./workshop-references"

it("summarizes repeated batch blockers without losing distinct reasons", () => {
  expect(summarizeWorkshopBlocks([{reason:"缺参考图"},{reason:"缺参考图"},{reason:"缺提示词"}])).toBe("2 组：缺参考图；1 组：缺提示词")
})
