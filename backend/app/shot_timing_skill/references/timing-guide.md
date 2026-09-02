# Shot Timing Guide (MiniMax H3 Director)

## 1. Speaking-rate budgets

Use these minimum durations before adding action/pause padding:

| Language | Pace | Chars or words per second | Minimum seconds |
| --- | --- | --- | --- |
| Chinese dialogue | normal | ~4 Han chars / s | `ceil(han_count / 4.0)` |
| Chinese dialogue | emotional / pause | ~3 Han chars / s | `ceil(han_count / 3.0)` |
| English dialogue | normal | ~2.5 words / s | `ceil(word_count / 2.5)` |

Add **+1.0s** when the speaker also walks, turns, or reacts during the line.
Add **+0.5s** per extra visible action beat in the same shot (max +2.0s unless duration exceeds 15s — then split the shot).

Clamp final `durationSec` to **2–15** (MiniMax H3 per-shot limit).

## 2. Action beats (Seedance-inspired)

Within one generated clip:

- **2–3s**: one primary subject action OR one camera move, not both at full intensity unless duration ≥ 6s.
- **5s clip**: at most **2** major action beats + **one** spoken line (≤ 15 Chinese chars at normal pace).
- **8–10s clip**: up to **3** action beats + one longer line or two short exchanges.
- If the story needs more, **split into another shot** instead of compressing.

## 3. promptText timeline syntax (H3)

Each shot is an independent `[Shot 1]` clip starting at local `00:00`.

```text
[Shot 1] A medium shot at eye level frames the alley. At 00:00.000, the detective stops under the neon sign. At 00:02.000, he turns toward the camera. The detective (S1) says: <d>[Chinese] 别动。</d> At 00:04.500, rain streaks across the lens as the camera holds static.
```

Rules:

- Beat times must stay **≤ durationSec** (use three decimal places in `At` markers).
- Place `<d>` at the second when speech **starts**, not after the clip ends.
- Leave **≥ 0.5s** after `<d>` ends before hard cut unless using `<cutoff>`.
- Do not write dialogue only in `dialogue` field without echoing it in `promptText` inside `<d>`.

## 4. Decision tree

1. Count dialogue length → compute `min_speech`.
2. Count major action beats → `min_action = 2 + (beats - 1) * 2.5`.
3. `recommended = ceil(max(min_speech, min_action))`, clamp 2–15.
4. If `recommended > 15` → split dialogue across two shots. Never shorten dialogue or use ellipsis.
5. If current `durationSec < recommended` → increase duration OR remove a non-essential action beat.
6. If no dialogue → duration driven by action only (usually 3–8s).

## 5. Examples

### Too tight (fix)

- dialogue: `你给我站住，不许动！` (10 chars)
- durationSec: 5
- Problem: line + walk-in needs ~4s speech + 2s action → use **7–8s** or drop walk-in.

### Good fit

- dialogue: `别动。` (3 chars)
- durationSec: 5
- promptText includes stop at 00:00, `<d>` at 00:01.5, hold until 00:04.

## 6. timingNote (Chinese, for humans)

When adjusting a shot, set `timingNote` briefly, e.g.:

- `对白 12 字偏长，时长 5s→8s，并在 prompt 加入 00:02 起句。`
- `动作过多，删除次要动作以保留完整对白，维持 8s。`
