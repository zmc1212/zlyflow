import { describe, expect, it } from "vitest"

import { PROMPT_INPUT_MAX_ROWS, promptAutoSize } from "./prompt-autosize"

describe("promptAutoSize", () => {
  it("保留各输入框的起始行数", () => {
    expect(promptAutoSize(2)).toEqual({ minRows: 2, maxRows: PROMPT_INPUT_MAX_ROWS })
    expect(promptAutoSize(5)).toEqual({ minRows: 5, maxRows: PROMPT_INPUT_MAX_ROWS })
  })

  it("起始行数超过封顶值时以起始行数为上限，避免输入框被压小", () => {
    const size = promptAutoSize(PROMPT_INPUT_MAX_ROWS + 4)
    expect(size.maxRows).toBe(PROMPT_INPUT_MAX_ROWS + 4)
    expect(size.maxRows).toBeGreaterThanOrEqual(size.minRows)
  })
})
