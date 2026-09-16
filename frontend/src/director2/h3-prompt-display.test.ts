import { describe, expect, it } from "vitest"
import { escapeHtml, renderH3PromptHtml } from "./h3-prompt-display"

describe("h3 prompt display", () => {
  it("escapes raw html before highlighting", () => {
    expect(escapeHtml('<img src=x onerror="alert(1)">')).toBe(
      "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;",
    )
    const html = renderH3PromptHtml('detailed_description:\n<script>alert(1)</script> <Picture 1> <Subject 2> [Shot 3]')
    expect(html).toContain('<span class="h3-section-key">detailed_description:</span>')
    expect(html).toContain('<span class="h3-ref-chip-inline"><span class="h3-chip-dot"></span>图片1</span>')
    expect(html).toContain('<span class="h3-subject-tag">&lt;Subject 2&gt;</span>')
    expect(html).toContain('<span class="h3-shot-tag">[Shot 3]</span>')
    expect(html).not.toContain("<script>")
  })
})
