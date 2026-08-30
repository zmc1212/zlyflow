# OpenCut timeline source mapping

This directory vendors adapted controller structure from:

- Repository: `https://github.com/OpenCut-app/opencut-classic`
- Commit: `cf5e79e919144200294fb9fed22a222592a0aeea`
- License: MIT (`LICENSE.OpenCut`)

Player transport additionally follows the matching five-button implementation in:

- Repository: `https://github.com/S07K/OpenCut`
- Commit: `e9c6cc06b549d7fa857bb8f43f02c47a39368e33`
- License: MIT (`LICENSE.Cutaway`)

Mappings:

| Local file | OpenCut source |
| --- | --- |
| `playhead-controller.ts` | `apps/web/src/timeline/controllers/playhead-controller.ts` |
| `resize-controller.ts` | `apps/web/src/timeline/controllers/resize-controller.ts` |
| `element-interaction-controller.ts` | `apps/web/src/timeline/controllers/element-interaction-controller.ts` |
| `zoom-controller.ts` | `apps/web/src/timeline/controllers/zoom-controller.ts` |
| `use-edge-auto-scroll.ts` | `apps/web/src/timeline/hooks/use-edge-auto-scroll.ts` |
| `use-committed-ref.ts` | `apps/web/src/hooks/use-committed-ref.ts` |
| `transport.ts` | `packages/timeline-engine/src/time.ts`, `packages/playback-engine/src/transport.ts` |
| `../components/PlayerTransport.tsx` | `apps/web/src/features/editor/PreviewPanel.tsx` |

The controllers retain OpenCut's explicit session state, committed config ref,
subscriber view updates, drag threshold, preview/commit split, and document-level
gesture capture. Adaptations replace `opencut-wasm` media ticks and arbitrary
multi-track operations with the director's 24fps contiguous `RecipeShot` track.
