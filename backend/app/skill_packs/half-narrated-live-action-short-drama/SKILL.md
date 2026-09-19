---
name: half-narrated-live-action-short-drama
description: "Create narration-led live-action drama from scripts and references: continuity assets, timed shots, assembly, narration, and optional subtitles. MiniMax-H3 default; check explicit alternatives."
trigger-words: [半解说真人短剧, 第一人称旁白短剧, 第三人称旁白短剧, 真人写实短剧, 竖屏短剧, 重生短剧, 末世短剧, 悬疑短剧, narrated live-action short drama]
---

> **工作台适配（非官方原文）**  
> 来源：Hub `half-narrated-live-action-short-drama` v1.0.1。下文为官方 Design 平台工作流，不要改写成另一套导演台阶段。  
> 映射：Design Image 2 → GRS；写稿可看整张 16:9 三联写运镜。成片走本地 MiniMax H3 R2V，只送角色卡、场景卡和三联**三格 9:16 裁切**（起幅=00:00 构图锚、中格=主动作构图、结果=落幅构图），禁止把整张 16:9 三联当 `<Picture n>`（本地 H3 会把三格插值成一条画面）；这三张是同一镜的时间路标，不是新人物；成片始终单一 9:16，禁止分栏、禁止把三格同时摆进画面。角色卡是多视图设定板，只锁身份/发型/服装，禁止把分格、白底、重复小人带进镜头。出片前由用户确认 **2K 或 768P**（整集统一），单镜 **5–15** 整数秒。第 10–11 步 Seed Audio 独立旁白轨与字幕本期不接线。导台2 阶段仍是 script → assets → episodes → storyboard，只注入本包约束。

# Half-Narrated Live-Action Short Drama

Use this Skill for end-to-end short-drama production on the Design platform. develop an idea, lock the story and visual bible, create character and scene cards, create keyframes, generate shot videos, verify the assembled video's real timeline, then generate a standalone Seed Audio narration track and subtitles. Focus on live-action-style narrated short dramas with realistic performances, grounded scenes, character dialogue, and voiceover-led storytelling. This is not a generic one-image, one-clip, animation, anime, pure-commentary, or ordinary-editing task.

## Core capabilities

- Develop a rough idea, theme, reference, or premise into a focused short-drama concept.
- Create and confirm the logline, characters, setting, episode structure, script, dialogue, and narration.
- Build reusable character and scene continuity anchors.
- Convert the approved script into a timed shot list and shot contracts.
- Generate character cards, scene cards, keyframes, shot images, and shot videos.
- Batch similar image work and generate connected shot videos.
- Assemble shots in story order, read the final video's real timeline, and generate one standalone Seed Audio narration track.
- Review continuity, lip-sync, framing, pacing, dialogue attribution, and final duration.

## Inputs

- A creative seed: idea, premise, theme, story fragment, script, or reference material.
- Optional character, costume, prop, location, style, storyboard, image, video, or audio references.
- Optional audience, platform, aspect ratio, duration, language, dialogue, narration, music, subtitle preference, and content constraints.
- Existing assets or an episode to continue, adapt, or remake.

## Production locks

- Default image model: `Design Image 2`.
- Default video model: `MiniMax-H3`.
- If the user explicitly selects another video model, check that it supports the required references, resolution, duration, dialogue, and lip-sync behavior before following that choice.
- Image generation uses 2K by default; video resolution is selected by the user as 2K or 768P before video generation.
- Video durations are integer seconds only. When using MiniMax-H3, every generated shot must be 5–15 seconds; merge adjacent short script beats when needed. For another explicitly selected model, use its verified supported limits without changing the approved story structure.
- When a video shot fails, retry that shot once after diagnosing the cause. If it still fails, switch the failed shot to another compatible available model instead of repeatedly forcing the same model.
- Do not change the production plan merely because image-generation capacity is unavailable at one moment. Keep the authored shot topology and continue with the affected item when execution is available.
- Do not add a separate capacity or safety-interception workflow to this Skill; follow the platform's normal execution result if a task cannot run.
- Keep subtitles off unless the user requests an SRT or burned subtitles.

## Workflow

### 1. Inspiration and concept

Extract the user's intent and references, then propose a focused direction: premise, genre, emotional hook, protagonist, conflict, world, and ending beat. Confirm the direction before detailed authoring.

### 2. Story and script

Create the short-drama structure for the requested duration: logline, character roles, scene progression, dialogue or narration, action beats, and ending. Keep spoken copy separate from visual direction. Confirm the script before expensive generation.

### 3. Character and scene cards

Create final character cards in 16:9 when they are used as identity references. Each character card must use a pure white background with no scene background, title, labels, or watermark; place a detailed facial close-up on the left and the same character's front, side, and back half-body views on the right. For live-action realism, write the card like a real casting / costume / continuity photo brief, not concept art: specify face shape, brow, eye shape and eyelids, nose bridge and wings, lips, jawline, hair silhouette, age cues, skin texture, natural facial asymmetry, clothing structure, fabric behavior, and identity-defining details. Explicitly preserve realistic body proportions, natural hands, believable wrinkles and wear, and avoid beauty-retouch, plastic skin, over-sharpened outlines, anime traits, CG-rendered looks, or stylized illustration cues.

Create scene cards in 16:9 with a pure white background and no people. A scene card must show the environment and equipment layout from useful views, preserving spatial relationships and recurring objects without inserting characters, body parts, silhouettes, reflections, readable UI, titles, or watermarks.

Use the final approved character cards and scene cards as the continuity sources for all downstream keyframes and videos. Do not reuse superseded cards when the user has reorganized or replaced the card group.

### 4. Storyboard and shot contract

Break the approved script into executable shots. Define each shot's final-video time range, integer duration, subjects, character-card mapping, scene-card mapping, action, spatial relation, framing, camera movement, dialogue or narration timing, keyframe need, transition, continuity handoff, and the exact prompt ingredients that must be carried into image and video generation. Merge adjacent story beats when a source line is shorter than 5 seconds. Keep every MiniMax-H3 shot between 5 and 15 integer seconds; use the verified limits of another explicitly selected model.

For each prompt, list all relevant role mappings explicitly: narrator, each named dialogue speaker, each character reference, scene reference, and keyframe reference. State which named characters appear and which do not appear. Preserve every supplied dialogue and narration line verbatim.

### 5. Keyframe generation

Keep the keyframe workflow. Generate one 16:9 keyframe master image for each executable video shot, and make the master image internally consist of three horizontally arranged 9:16 vertical sub-keyframes. The three sub-keyframes should represent different visual portions of the same shot, ordered as: spatial establishment / main action / result or emotional resolution. They must share the same character, scene, and prop continuity, but each sub-frame must present clearly different composition, visual focus, and storytelling information. Keyframes must represent the shot's actual composition, subject placement, action start, and continuity handoff. Use the final character cards for identity, the final scene card for world/layout, and the storyboard for shot-specific composition. For live-action projects, keyframes must look like grounded cinematography references or continuity storyboard boards: stable human anatomy, realistic clothing physics, natural expression range, and no illustration, toy-model, waxy-skin, poster-art styling, or repeated near-identical close-ups across the three panels. Review keyframes before video generation.

### 6. Image generation

Generate character cards, scene cards, keyframes, and shot images with `Design Image 2` at 2K by default. Use the approved reference roles and preserve identity, subject count, scene geography, and required visual traits. For any live-action project, the prompt must explicitly push photographic realism: cinematic still / continuity photo / casting photo language, realistic lighting, natural skin texture, believable pores and fine hair strands, physically plausible clothing folds, correct lens perspective, and restrained color grading. Do not create unrequested text, titles, watermarks, or background elements, and do not let the output drift into polished AI beauty render, illustration, or CG poster style.

### 7. Video resolution confirmation

Before generating any video, ask the user to choose the output resolution: `2K` or `768P`. Treat the user selection as a production lock and use the same confirmed resolution for every shot in the episode. Do not silently choose, change, or mix resolutions after confirmation.

### 8. Video generation

Generate each approved shot with `MiniMax-H3` by default at the user-confirmed 2K or 768P resolution and an integer duration from 5 to 15 seconds. If the user explicitly selected another model and its capability check passed, apply the same approved shot contract within that model's supported resolution, duration, reference, dialogue, and lip-sync limits. For a single video task or shot, timecodes must start from `00:00`; do not carry over upstream storyboard segment timestamps. When MiniMax-H3 is active, read `references/h3-video-prompt-template.md` and fill it in before generation. Use the three-panel keyframe master as the shot's visual anchor when the storyboard calls for it, together with the mapped character and scene cards. Preserve the established character, world, action, camera intent, dialogue timing, and visual style. For live-action projects, explicitly demand photographic realism in the prompt: documentary / drama still / cinema verité / handheld or locked-off camera as appropriate, believable depth of field, natural motion blur, physical facial motion, no anime or CG language, no glossy beauty-filter look, and no exaggerated AI facial symmetry.

Every video prompt must divide the shot into clear internal content beats based on narration, dialogue, and image content: first establish the space and character relationships, then show the narration-linked visuals, then show the dialogue action and reaction, and finally close on the resulting emotional state; if the shot needs a visual shift or information change, the prompt may explicitly ask for an internal cut, push-in, reveal, occlusion-based reveal, or spatial transition, but only within the same approved shot number and total duration. During narration, the narrated subject keeps their mouth closed unless they have a separate dialogue cue. During dialogue, only the assigned speaker performs lip-sync. Keep each character's voice role distinct in the prompt.

### 8.1 Video prompt assembly order

Build every video prompt from the following fixed order so the prompt stays grounded and the visual style does not drift:
1. Shot purpose and exact time range.
2. Locked identity sources: character cards, scene card, and three-panel keyframe reference.
3. Visual realism target for live-action projects: cinematography / continuity-photo language.
4. Narrative-linked visuals and dialogue-linked visuals.
5. Subject blocking: who is on screen, who is not, and where they are placed.
6. Action beat and emotional state.
7. Camera framing and movement, including any internal cut, push-in, reveal, occlusion-based reveal, or spatial transition.
8. Dialogue, narration, and exact lip-sync owner.
9. Continuity constraints: costume, props, wetness, lighting, injury, and spatial handoff.
10. Negative constraints: no illustration, no CG, no beauty-filter look, no facial symmetry exaggeration.

Do not write the shot prompt as a freeform paragraph if the shot has multiple roles, transitions, or continuity constraints; assemble it from the template order. Internal cuts or transitions are only allowed within the shot itself and must not change shot number or total duration.

If a shot execution fails, preserve successful shots and retry only the missing shot once after diagnosing the cause. If the retry still fails, switch only that shot to another compatible available model. Do not rebuild the full project, repeatedly force the same model, or change the shot topology for a transient execution issue.

### 9. Assemble the final video

Order the generated shots by authored shot number, not by canvas return order. Merge them into the final video, then read that final video's actual media duration, actual shot boundaries, and real visual ending time. Use this as the only timing basis for the later narration audio. Do not split original audio, audit preserved dialogue, or perform final audio mixing.

### 10. Final narration generation

Before composing the final Seed Audio prompt, read `references/seedaudio-final-track-prompt-template.md` and use its structure. This template is only for generating one standalone narration audio file from the final assembled video's real timeline. Do not split original-video narration and dialogue. Do not preserve original dialogue as an audio source. Do not build a final mixed audio track.

After the final video is assembled, extract the actual final-video timeline and reconcile narration with the visuals only. Produce a final narration table with:

- exact start and end timestamp
- speaker role
- verbatim narration line
- audio source: Seed Audio narration / absolute silence
- any timing correction required by the actual final video

Use Seed Audio to generate only the narration audio. Put the complete narrator voice map, exact narration timestamps, voice descriptions, silence requirements, and narration lines into the generation prompt's text field. Keep the narration voice stable and distinct. Unless the user explicitly requests otherwise, disable BGM, ambience, room tone, breath noise, transition sounds, and all sound effects. All intervals without a timestamped narration line must be absolute silence. Set the narration audio target length from the real assembled-video duration, not from the planned storyboard duration. Generate the standalone narration from the confirmed final-video timeline. Do not split the original audio, preserve dialogue as an audio source, or create a mixed-audio video within this Skill.

### 11. Deliver final video, subtitles, and narration audio

Deliver three independent outputs: the final assembled video, the subtitle file, and the standalone Seed Audio narration file. Do not mix the narration audio back into the video, and do not create another mixed-audio version. Generate subtitles from the final video timeline and narration script; if the user requests SRT or burned subtitles, use the final assembled video's real timeline.

## Outputs

- Approved concept and short-drama premise.
- Script, narration, dialogue, scene breakdown, and timing structure.
- Final 16:9 pure-white character cards with facial close-ups and three half-body views.
- Final 16:9 pure-white person-free scene cards.
- 9:16 keyframes and shot-level contracts.
- 2K integer-second images and video assets from MiniMax-H3 by default, or from a capability-checked model explicitly selected by the user.
- One standalone Seed Audio narration file aligned to the actual assembled-video timestamps.
- The final assembled video, plus SRT or burned subtitles when requested.
- Optional SRT or burned subtitle version when requested.

## Boundaries

This Skill is for Design-platform short-drama production. It does not cover external provider setup, API-key management, image hosting, local Electron installation, or unrelated standalone retouching. It does not silently change approved character identity, scene geography, speaker attribution, script wording, shot order, or user-selected output constraints.

## Provenance

This Skill is designed for continuity-controlled narrated live-action short-drama episodes.
