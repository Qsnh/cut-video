---
name: cut-video
description: Edit a recorded video for TikTok, Douyin and other platforms, whether a talking head (口播), a narrated screen recording, a tutorial or a silent clip. Use for any combination of filler removal (去语气词), trimming or removing sections (掐头去尾、删掉一段), synchronized Chinese captions, iPhone exposure correction, playback speed (倍速), a decorative background behind the picture (视频背景), a new voice or narration in a Doubao voice (换音色、配音), translated or bilingual captions and dubbing into another language (多语言、翻译、双语字幕), or moving a spoken hook to the opening.
---

# Cut a video

The edits below stand side by side, and one request may combine any of them: remove fillers, trim or remove sections, move a hook to the opening, correct exposure, add captions, change the speed, add a background, change the voice, translate. Fillers, trims and the hook shape one plan of kept intervals; the rest are renderer options. Make the edits the user asks for in one plan and one render, whatever the video is.

Start from the most recent edit the user approved. “Cut my video for TikTok” on a recording with speech defaults to removing its fillers while keeping the whole content and its argument. Create a highlight when the user asks for one.

## Inspect the input and plan the edit

1. Locate the input and inspect its displayed orientation, frame rate, transfer, primaries and audio. A source without an audio track has no speech to edit and is delivered as a silent MP4. For iPhone MOVs with multiple audio tracks, audition the selected one. Keep the source and approved exports and give each delivery a fresh name.
2. Record the **kept** intervals on one constant-frame-rate timeline, with inclusive starts and exclusive ends. Use that timeline for picture, audio and captions. An interval ending in `null` runs to the last frame, so `{"fps": 30, "keep": [[0, null]]}` keeps the whole video when only its speed, background or exposure changes. The bundled renderer preserves the order listed, splits the work into decoder runs and checks the delivered frame count and duration. See [commands and plan format](references/render.md).

## When removing fillers

Any recording with speech can carry fillers, whether a talking head, a narrated screen recording or a tutorial.

1. Locate possible fillers with the **local** word-timed transcript. The bundled finder cuts long recordings at nearby quiet moments, saves each chunk when it finishes so an interrupted run resumes, and re-decodes a chunk whose output collapsed into a repetition loop. “嗯、啊、呃”, “um” and “uh” are useful search targets. A question-ending “呢”, a meaningful acknowledgement or a speaker quoting someone may carry meaning.
2. Check each proposed cut against the surrounding sentence and the audio waveform. Recognizers can omit fillers, invent them in silence, or assign a vowel to the preceding word. Find the actual sound and keep consonant attacks and word endings audible. Retain natural breaths. Leave ambiguous syllables in the talk.
3. Cut **inside the gap between two words** instead of shortening the pause by a fixed margin: a filler frequently sits in that margin, so a first pass that keeps 0.3 seconds after each removed hesitation leaves some of them behind. Confirm the boundary with the waveform rather than the timestamp alone.
4. Validate the plan before rendering with the bundled checker, then re-transcribe the cut and repeat the search on that transcript. A plan that straddles one syllable loses it audibly, and a single pass routinely leaves a fifth of the fillers. Content characters must match the source transcript exactly when the search comes back empty — that equality is the cheapest proof the edit removed only fillers and pauses.

## When trimming or removing sections

Turn the request into removed ranges: “去掉前 5 秒”, “只要 1:20 到 2:05”, “删掉中间卡住的那段”. Convert each time with `round(seconds * fps)` and take the ranges out of the kept intervals. When the user names a moment rather than a time (“the part where the page loads”), find it on frames sampled around the likely place. Confirm each boundary on the frames either side, and move one that falls in speech into the gap between two words. List the ranges under `drop` in the plan as well, so the checker counts their speech as removed on purpose rather than lost ([plan format](references/render.md#represent-an-edit)). The passages a highlight leaves out go under `drop` the same way.

## When adding a hook

Use the specific claim the user chose. Find a complete spoken question or judgment that lands in the first two seconds. Preserve qualifiers, the speaker's position and the answer's context. Cut into the actual voice, then return to the story at a natural sentence boundary. For “move this section to the front”, put the chosen intervals first and remove their old occurrence. Check how the sentences on either side of the old location now read together. A short first-frame headline can supply context when the user wants a stronger opening. Retention can be measured after publication.

## When adjusting exposure or adding captions

- For a bright iPhone recording, return to the original HDR picture and reuse the approved cuts. Compare representative frames before encoding. Look for detail in the face, white clothing and bright background. The renderer includes a tunable HLG/BT.2020 to SDR/BT.709 transform. Choose the treatment from the source metadata and the preview.
- Caption only from text that exists: the recorded speech or text the user supplies. Never invent narration. Write short cues in the speaker's language, or in the language the user asks for, timed to the **edited** speech. Check names, numbers, negations and terms such as “Agent” against context. Break lines at a phrase boundary. For portrait video, use one or two high-contrast lines below the face and above the platform controls. Inspect the result with the actual speaker and font.
- Burned-in captions default to white text on a translucent dark box. When the user asks for a different look — a white or yellow box, outlined text, yellow variety-show text or a drop shadow — pick the matching `--caption-style` ([styles](references/render.md#render)). If they ask without naming one, render a short preview in a few styles and let them choose.
- Keep one cue under 23 Han characters, which is the most that fits one line at the renderer's smallest accepted size regardless of frame width; use an explicit line break for two longer lines. Merge cues shorter than four characters into a neighbour so the text does not flicker. A cue crossing a cut is kept only on the footage that survives, so rewrite it when removed words were part of it.
- Name the font face explicitly for Chinese. On macOS `/System/Library/Fonts/STHeiti Medium.ttc` carries Simplified glyphs at index 1 and Traditional glyphs at index 0, so a wrong index renders correct text in the wrong regional forms; `PingFang.ttc` is absent on current systems. Confirm the chosen index reports a Simplified name before burning the whole talk. A font the user names or supplies goes to `--burn-font` the same way; the renderer refuses one that lacks any caption character.
- A source-timed SRT can be remapped through cuts and reordered sections. Supply the corrected final-timeline SRT for burn-in. If working from an already captioned export, its existing captions move with the picture; update the sidecar and render new text only where the picture needs it.

## When changing playback speed

When the user asks for a faster or slower delivery (“1.25 倍速”), pass `--speed` to the renderer instead of editing the plan; it accepts 0.5 to 5. The plan, the filler review and any supplied SRT stay on the normal-speed timeline, and the renderer scales picture, voice and captions together. The voice keeps its pitch. The delivered SRT is on the sped-up timeline, so it must not be supplied again as `--edited-srt` for another render. Speech becomes hard to follow above about 1.5×, so preview a short plan at the chosen speed before the whole talk. Above 2× the result is a fast-forward rather than listenable speech, and rescaled captions pass too quickly to read; ask whether to drop them or write fewer, longer cues for the delivered timeline. The delivered duration is the kept duration divided by the speed.

## When adding a background

When the user asks for a background (视频背景), such as the picture as a rounded card on a wallpaper or gradient, pass `--background` to the renderer ([values](references/render.md#background)). It takes a gradient preset (`sunset`, `spring`, `ocean`, `dusk`, or `random`), a colour, an image file, or `blur` for the picture itself blurred behind the card. The frame keeps its size and orientation, and `--padding` and `--radius` widen the margin or round the corners. Burned-in captions are laid out on the card: below the face on portrait, near the card's bottom edge on landscape. A wallpaper the user names, including the macOS ones under `/System/Library/Desktop Pictures`, is passed as its path; never copy one into the skill. If they ask without naming a background, render a short preview on a few and let them choose. `random` prints the preset it picked; name it in the report.

## When changing the voice

When the user asks for another voice (换音色) or for narration over a silent recording (配音), pass `--voice` with a Doubao Speech voice ID to the renderer ([voices and limits](references/render.md#voice)). It reads the caption cues aloud in that voice and replaces the recorded sound, so it needs `--source-srt` or `--edited-srt`; burning the captions in stays optional. Voice only text that exists: the corrected transcript of the speech, or text the user supplies. Speak from a final-timeline SRT whose text is exactly the kept speech, passed as `--edited-srt` whenever the plan cuts inside a cue: a remapped source cue keeps its whole text, so the voice would read removed fillers and trimmed words aloud, or a moved hook twice. For a silent recording, time each sentence of the supplied text to the picture it describes. Default to `zh_female_vv_uranus_bigtts` (Vivi 2.0) when the user names no voice; if they ask for a choice, render a short preview in two or three voices and let them pick.

The renderer needs a Doubao Speech API key in `DOUBAO_API_KEY`. Ask the user for one when it is missing, pass it in the environment, and never write it into the skill, the plan or the user's folders. Only the cue text leaves the machine. Tell the user before rendering a talking head that the lips will not follow the new voice, and that music and room sound go with the old one.

Each cue is spoken from its start and may run on into the pause before the next cue, where its caption is extended to match. A sentence that still does not fit is read faster: the renderer lists cues hurried beyond 1.25× and refuses any that would need more than 1.5×, so give such a cue more time or split it across two. `--voice-rate` sets the pace from 0.5 to 2, and `--speed` makes the voice read faster on top of it. Transcribe the delivered video and compare it with the cues: names, numbers and mixed Chinese and English are where a voice misreads.

## When translating

When the user asks for the video in another language (英文版、日语配音) or for translated or bilingual captions (双语字幕), translate the corrected final-timeline cues one for one and keep each cue's times, so every sentence stays on the picture it describes. Translate only what was said or supplied, in the speaker's register. Keep names, numbers, negations and terms such as “Agent”. Save the translation as a new SRT for `--edited-srt` and keep the original beside it.

- Translated captions over the original voice need nothing more. For bilingual captions, put the original line above its translation in each cue, one line of each, in a font that carries both scripts.
- For a dub, add `--voice` and the translation's `--voice-language`, `en` included ([languages](references/render.md#languages)). A voice told nothing reads only Chinese and English: it reads French with English sounds, returns nothing for Japanese, and reads a cue of bare digits such as “100%” in Chinese. The renderer refuses cues with other letters until the language is named. The voice reads every line of a cue, so a dubbed cut carries captions in the dub's language alone. Vivi 2.0 stays the default; an English voice such as `en_male_tim_uranus_bigtts` sounds more native in English, so include one when previewing voices for an English dub.
- A translation usually takes longer to say. Write each cue to fit its time, about three English words a second at the voice's own pace, and tighten the wording rather than drop meaning. The renderer lists cues it hurried and refuses any beyond 1.5×; shorten those or merge one with its neighbour.
- Break a line of a language written with spaces before 42 characters, fewer in capitals; Japanese and Korean keep the 23-character limit. Choose a font with the language's letters and regional forms ([fonts](references/render.md#languages)): a Chinese font draws Japanese kanji in Chinese forms. Arabic, Hindi and Thai burn in only where Pillow has its Raqm layout; otherwise deliver their SRT for the platform's own captions.
- Transcribe the delivered video in the target language and compare it with the cues.

## Deliver and verify

Export a separate playable MP4. When captions are requested, deliver the matching SRT alongside the captioned video. Review the first two seconds, both sides of moved passages, several ordinary cuts, and the final word. Check lip sync (with a new voice, that each sentence starts with its caption) and caption placement near the beginning, middle and end. Where there is no speech, review the frames on both sides of each cut and the last frame instead. Report what changed, the duration, and links to the finished files. The deliverable for a publishing request phrased as “I will publish” is the local upload-ready file.

Rendering writes scratch files beside the output as a hidden `.cut-video-*` folder, which stays behind if the process is killed. Point `--workdir` at the agent's working directory for long jobs, and mention any leftover folder rather than deleting files in the user's folders.
