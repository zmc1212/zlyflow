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

Do not emit Seedance platform markers, Markdown clip packs, or Seedance API control claims into MiniMax H3 prompts.
