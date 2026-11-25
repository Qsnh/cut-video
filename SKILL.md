---
name: cut-talking-video
description: Edit recorded talking-head videos for TikTok or Douyin. Use for full-talk filler removal (口播剪辑、去语气词), synchronized Chinese captions, iPhone exposure correction, playback speed (倍速), a decorative background behind the picture (视频背景), or moving a spoken hook to the opening.
---

# Cut a talking video

Start from the most recent edit the user approved. For this workflow, “cut my video for TikTok” defaults to keeping the whole talk and its argument. Create a highlight when the user asks for one. Apply exposure changes, subtitles and a hook when requested, or together when the user asks for the full workflow.

## Make the speech edit

1. Locate the input and inspect its displayed orientation, frame rate, transfer, primaries and playable dialogue track. For iPhone MOVs with multiple audio tracks, audition the selected one. Keep the source and approved exports and give each delivery a fresh name.
2. Locate possible fillers with the **local** word-timed transcript. The bundled finder cuts long recordings at nearby quiet moments, saves each chunk when it finishes so an interrupted run resumes, and re-decodes a chunk whose output collapsed into a repetition loop. “嗯、啊、呃”, “um” and “uh” are useful search targets. A question-ending “呢”, a meaningful acknowledgement or a speaker quoting someone may carry meaning.
3. Check each proposed cut against the surrounding sentence and the audio waveform. Recognizers can omit fillers, invent them in silence, or assign a vowel to the preceding word. Find the actual sound and keep consonant attacks and word endings audible. Retain natural breaths. Leave ambiguous syllables in the talk.
4. Cut **inside the gap between two words** instead of shortening the pause by a fixed margin: a filler frequently sits in that margin, so a first pass that keeps 0.3 seconds after each removed hesitation leaves some of them behind. Confirm the boundary with the waveform rather than the timestamp alone.
5. Record the **kept** intervals on one constant-frame-rate timeline, with inclusive starts and exclusive ends. Use that timeline for picture, audio and captions. The bundled renderer preserves the order listed, splits the work into decoder runs and checks the delivered frame count and duration. See [commands and plan format](references/render.md).
6. Validate the plan before rendering with the bundled checker, then re-transcribe the cut and repeat the search on that transcript. A plan that straddles one syllable loses it audibly, and a single pass routinely leaves a fifth of the fillers. Content characters must match the source transcript exactly when the search comes back empty — that equality is the cheapest proof the edit removed only fillers and pauses.

## When adding a hook

Use the specific claim the user chose. Find a complete spoken question or judgment that lands in the first two seconds. Preserve qualifiers, the speaker's position and the answer's context. Cut into the actual voice, then return to the story at a natural sentence boundary. For “move this section to the front”, put the chosen intervals first and remove their old occurrence. Check how the sentences on either side of the old location now read together. A short first-frame headline can supply context when the user wants a stronger opening. Retention can be measured after publication.

## When adjusting exposure or adding captions

- For a bright iPhone recording, return to the original HDR picture and reuse the approved cuts. Compare representative frames before encoding. Look for detail in the face, white clothing and bright background. The renderer includes a tunable HLG/BT.2020 to SDR/BT.709 transform. Choose the treatment from the source metadata and the preview.
- Write short cues in the speaker's language, timed to the **edited** speech. Check names, numbers, negations and terms such as “Agent” against context. Break lines at a phrase boundary. For portrait video, use one or two high-contrast lines below the face and above the platform controls. Inspect the result with the actual speaker and font.
- Burned-in captions default to white text on a translucent dark box. When the user asks for a different look — a white or yellow box, outlined text, yellow variety-show text or a drop shadow — pick the matching `--caption-style` ([styles](references/render.md#render)). If they ask without naming one, render a short preview in a few styles and let them choose.
- Keep one cue under 23 Han characters, which is the most that fits one line at the renderer's smallest accepted size regardless of frame width; use an explicit line break for two longer lines. Merge cues shorter than four characters into a neighbour so the text does not flicker. A cue crossing a cut is kept only on the footage that survives, so rewrite it when removed words were part of it.
- Name the font face explicitly for Chinese. On macOS `/System/Library/Fonts/STHeiti Medium.ttc` carries Simplified glyphs at index 1 and Traditional glyphs at index 0, so a wrong index renders correct text in the wrong regional forms; `PingFang.ttc` is absent on current systems. Confirm the chosen index reports a Simplified name before burning the whole talk. A font the user names or supplies goes to `--burn-font` the same way; the renderer refuses one that lacks any caption character.
- A source-timed SRT can be remapped through cuts and reordered sections. Supply the corrected final-timeline SRT for burn-in. If working from an already captioned export, its existing captions move with the picture; update the sidecar and render new text only where the picture needs it.

## When changing playback speed

When the user asks for a faster or slower delivery (“1.25 倍速”), pass `--speed` to the renderer instead of editing the plan; it accepts 0.5 to 5. The plan, the filler review and any supplied SRT stay on the normal-speed timeline, and the renderer scales picture, voice and captions together. The voice keeps its pitch. The delivered SRT is on the sped-up timeline, so it must not be supplied again as `--edited-srt` for another render. Speech becomes hard to follow above about 1.5×, so preview a short plan at the chosen speed before the whole talk. Above 2× the result is a fast-forward rather than listenable speech, and rescaled captions pass too quickly to read; ask whether to drop them or write fewer, longer cues for the delivered timeline. The delivered duration is the kept duration divided by the speed.

## When adding a background

When the user asks for a background (视频背景), such as the picture as a rounded card on a wallpaper or gradient, pass `--background` to the renderer ([values](references/render.md#background)). It takes a gradient preset (`sunset`, `spring`, `ocean`, `dusk`, or `random`), a colour, an image file, or `blur` for the picture itself blurred behind the card. The frame keeps its size and orientation, and `--padding` and `--radius` widen the margin or round the corners. Burned-in captions are laid out on the card: below the face on portrait, near the card's bottom edge on landscape. A wallpaper the user names, including the macOS ones under `/System/Library/Desktop Pictures`, is passed as its path; never copy one into the skill. If they ask without naming a background, render a short preview on a few and let them choose. `random` prints the preset it picked; name it in the report.

## Deliver and verify

Export a separate playable MP4. When captions are requested, deliver the matching SRT alongside the captioned video. Review the first two seconds, both sides of moved passages, several ordinary cuts, and the final word. Check lip sync and caption placement near the beginning, middle and end. Report what changed, the duration, and links to the finished files. The deliverable for a publishing request phrased as “I will publish” is the local upload-ready file.

Rendering writes scratch files beside the output as a hidden `.talk-edit-*` folder, which stays behind if the process is killed. Point `--workdir` at the agent's working directory for long jobs, and mention any leftover folder rather than deleting files in the user's folders.
