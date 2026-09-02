# Continuity guide (Seedance-inspired, MiniMax H3)

## Scene ledger (script and storyboard)

Use this before writing prompts. Keep it short and observable.

```text
Scene: [location / time]
Visual anchors: [lighting source, wardrobe, stable set features]
Opening state: [characters, positions, eyelines, props, ongoing sound]
Beat: [one visible dramatic change]
Closing state: [final positions, prop changes, emotional turn]
Unknowns: [facts that still need confirmation — do not invent]
```

For the `script` agent, fold these into Chinese `fullStory` scene blocks so later splitting inherits them.
For the `storyboard` agent, map opening → `continuityIn`, closing → `continuityOut`, and name the cut in `transitionNote`.

## Clip handoff pattern

Each H3 clip is still one independent request. Mentally follow Seedance start/end state structure, then store the edges:

1. **Start state** → `continuityIn` + the first `At 00:00.000` beat in `promptText`
2. **Camera and action** → one playable change inside `durationSec`
3. **Dialogue and sound** → verbatim `<d>` lines + `soundscapeEn`
4. **End state** → `continuityOut` + the final beat before the clip ends

Compiler wrapping (do not write these wrappers yourself during polish unless editing the final H3 body):

- `Continuity at clip opening: ...`
- `End this clip on: ...`

## Bridge types for `transitionNote`

Prefer one short Chinese note:

- 动作匹配切 — outgoing motion continues into the next opening pose
- 视线匹配切 — eyeline / look direction carries across the cut
- 方向匹配切 — screen-direction or travel axis stays consistent
- 声音桥 — ambience, rain, footsteps, or dialogue continues across the cut
- 硬切换场 — intentional change of time/place/subject; only narrative or audio bridge remains

## Continuity rules

- A state describes the first or last visible frame, not a future instruction.
- When a character crosses a room, record both final position and the changed object/character relationship.
- Preserve injury, moisture, dirt, costume damage, held objects, time of day, and lighting unless the script changes them.
- Do not assert a face, garment, prop, or room detail that has not been supplied or approved.
- If a supplied reference conflicts with the script, surface the conflict rather than silently choosing one.
- Never use accumulated film timecode. Every clip resets to `00:00`.
- Never emit `[Shot 2+]`, `At 00:11.000, the camera cuts to`, or Seedance Markdown prompt-pack headings into H3 fields.

## Adjacent-cut QA checklist

After polishing an ordered shot list:

1. Shot N `continuityOut` should be re-usable as Shot N+1 `continuityIn` (same people/props/light/direction, or an explicit hard-cut reason).
2. `promptText` opening and final beats agree with those boundary states.
3. Dialogue lines are still present and verbatim.
4. `durationSec` still fits speech + one primary action.
5. No invented character, costume, prop, or event appeared.
6. `transitionNote` names the bridge; it is not copied into `promptText`.

## Failure modes

| Failure | Fix |
| --- | --- |
| Next clip resets wardrobe / wetness / held prop | Rewrite `continuityIn` from previous `continuityOut` |
| Cut claims seamless join across a location jump | Change to deliberate hard cut; keep only intended bridge |
| Boundary state is a plot summary | Rewrite as visible frame facts |
| Opening beat fights `continuityIn` | Align the first `At 00:00.000` action with the opening state |
| Only visual I2V is used, no text handoff | Keep both: text continuity for every cut, optional end-frame anchor when the user enables it |
