# Source note

Continuity and scene-ledger doctrine adapted for MiniMax H3 director studio from the local Seedance 2.5 skill:

- `references/production-contract.md` — scene ledger, continuity rules, dialogue timing
- `references/prompt-patterns.md` — Start state / End state clip structure
- `references/route-templates.md` — Narrative / short drama route
- `scripts/validate_prompt_pack.py` — multi-clip continuity QA idea

This vendored skill is for **ZLY Director Studio / MiniMax H3**:

- Each shot remains an independently renderable clip whose local timeline starts at `00:00`.
- Boundary states are stored as `continuityIn` / `continuityOut` (English) and compiled as handoff prose.
- `transitionNote` is a Chinese editorial note for humans; it is not pasted into the H3 body.
- Visual I2V inheritance (`usePreviousEndFrame`) stays a separate, user-controlled anchor.

Director-2 content-library import (`shot_plan`) uses a separate Chinese contract in `references/import-shot-plan-continuity.md`:

- Fields are `opening_state` / `closing_state` / `transition_note` (Chinese), not Recipe `continuityIn` / `continuityOut`.
- Opening pose must also be written into `action` prose so workshop beats still lock sit/stand if a later step misses the new fields.
- Same-scene causal cuts inherit the previous landing pose; do not invent a stand-up to "catch a book."
- Visual I2V end-frame chaining is still out of scope for this import path.

Do not emit Seedance platform markers, Markdown clip packs, or Seedance API control claims into MiniMax H3 prompts.
