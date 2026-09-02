---
name: shot-timing-budget
description: Budget MiniMax H3 shot duration, dialogue, and promptText beats second-by-second. Use when splitting storyboards, polishing shots, or rewriting promptText so spoken lines and visible actions fit inside durationSec (2–15s).
compatibility: Local skill for ZLY AI Video Studio director agents. No external API. Methodology inspired by Seedance timestamp prompting, adapted to MiniMax H3 At 00:00.000 notation and <d> dialogue tags.
---

# Shot Timing Budget (H3 Director)

## When to use

- After a storyboard draft exists and before video/TTS submission.
- When dialogue feels rushed, truncated, or longer than the clip duration.
- When promptText packs too many actions into a 5-second clip.

## Workflow

1. Read each shot's `durationSec`, `dialogue`, `description`, and `promptText`.
2. Estimate the minimum speakable duration for dialogue (see `references/timing-guide.md`).
3. Estimate action beats (roughly one primary visible action every 2–3 seconds).
4. Set `durationSec` to fit both dialogue and action, clamped to 2–15 seconds.
5. If dialogue still does not fit, split into another shot — never trim words or use ellipsis in dialogue or <d>.
6. Rewrite `promptText` as one `[Shot 1]` clip with `At HH:MM.SSS` beats inside the chosen duration.
7. Write a short Chinese `timingNote` when you changed duration, dialogue, or beats.

## Output rules

- Preserve `shotNumber`, bindings, camera, and story meaning.
- Do not invent new shots unless splitting is required to keep dialogue speakable.
- Keep dialogue inside `<d>[Chinese|English] ...</d>` in `promptText` when the line is spoken on screen.
- Match the last beat time to `durationSec` (two decimal places in alignment lines, three in `At` markers).

Read `references/timing-guide.md` for formulas, examples, and failure modes.
