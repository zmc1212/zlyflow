---
name: shot-continuity-handoff
description: Plan and polish adjacent MiniMax H3 shot handoffs so a storyboard reads as one continuous edit while every clip stays independently renderable. Use when writing scripts, splitting storyboards, or refining continuityIn / continuityOut / transitionNote.
compatibility: Local skill for ZLY AI Video Studio director agents. No external API. Methodology inspired by Seedance 2.5 scene ledgers and start/end-state prompt packs, adapted to H3 independent clips.
---

# Shot Continuity Handoff (H3 Director)

## When to use

- Expanding a one-line idea into a shootable Chinese script (`script` agent).
- Splitting a full script into ordered shots (`storyboard` first pass).
- Polishing adjacent cuts after timing is locked (`storyboard` continuity pass).
- Checking that compiled H3 prompts still open and close on inheritables states.

## Workflow

1. Treat the ordered storyboard as one continuous edit.
2. For every scene or shot, lock a miniature scene ledger first:
   - visual anchors (time, light, wardrobe, stable set)
   - opening state (who, where, eyeline, props, motion/sound already in progress)
   - one playable dramatic change
   - closing state the next clip can inherit
3. Write each MiniMax H3 `promptText` as an independent `[Shot 1]` clip starting at `00:00`.
4. Carry confirmed state forward across cuts. Do not reset people, props, location, lighting, injury, moisture, costume damage, or held objects unless the script changes them.
5. Store English boundary states in `continuityIn` / `continuityOut`. Store a short Chinese editorial bridge in `transitionNote`.
6. When the story intentionally changes time, place, or subject, mark a deliberate hard cut. Preserve only the intended narrative or audio bridge; do not fake a seamless physical join.

## Field contract

| Field | Language | Role |
| --- | --- | --- |
| `continuityIn` | English | Visible state at this clip's `00:00` |
| `continuityOut` | English | Final-frame state the next clip can inherit |
| `transitionNote` | Chinese | Human-facing bridge name (match action / match look / direction / sound / hard cut) |
| `promptText` | English | Independently renderable H3 body; opening and final beats must agree with the boundary states |
| `usePreviousEndFrame` | boolean | Optional visual I2V anchor; never force it during LLM polish |

## Output rules

- First shot may leave `continuityIn` empty; final shot may leave `continuityOut` empty.
- Every middle cut needs both sides of the handoff.
- Boundary states describe the first or last visible frame, not future instructions.
- Do not invent characters, costumes, props, dialogue, events, or reference tags.
- Keep dialogue verbatim; silent reaction/insert cuts must not hide a change in dialogue, space, or causality.

Read `references/continuity-guide.md` for templates, bridge types, and failure modes.
