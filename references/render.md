# Running the editor

Use paths relative to the skill directory in these commands. Python 3, NumPy, FFmpeg 4.4 or later and FFprobe run the cut and color steps. Burn-in uses Pillow and a local font containing the caption characters; Arabic, Hindi and Thai captions also need Pillow's Raqm layout ([languages](#languages)). Candidate discovery additionally uses the Python package openai-whisper, PyTorch and a local multilingual Whisper checkpoint for Chinese. An existing word-timed transcript can also supply the candidate list. A new voice calls Doubao Speech over HTTPS with an API key in `DOUBAO_API_KEY`.

## Find and review possible fillers

```sh
python3 scripts/find_fillers.py input.MOV words.json --model /path/to/small.pt --language zh
```

The JSON contains source-second word timings, recognition probabilities and candidate context. Each chunk is saved to `words.json.parts/` as it completes, so a cancelled or interrupted run resumes where it stopped; pass `--parts other/dir` to keep chunks elsewhere, and delete that folder once the edit is approved. Chunks are derived from the audio, so an interrupted run keeps its numbering.

A decode that collapses into a repetition loop invents speech and shifts every later timestamp. The finder re-decodes such a chunk at `beam_size=5` and reports the range when both attempts still loop; treat a reported range as unverified and listen to it. A repaired range is worth one more look at its neighbours, because a collapse also hides the words around it:

```sh
ffmpeg -v error -ss 28 -i input.MOV -t 16 -map 0:a:0 -ac 1 -ar 16000 review.wav
```

Use a small batch of suspected fillers to refine the edit before processing the rest of the talk. Whisper can give a clearly audible “呃” identical start and end timestamps. Treat that time as a search point: inspect roughly half a second on either side, widen to include the neighboring words when needed, and set the boundaries from the sound. A detected quiet interval alone is insufficient evidence of a filler.

## Represent an edit

Choose the delivery frame rate from the recording and the user's intended output. A phone's variable frame rate can be normalized to its nominal rate. For 29.97 use the exact fraction `"30000/1001"`. Convert a reviewed time in seconds to a source frame with `round(seconds * fps)`. For a whole-talk cleanup, sort and merge the removed ranges, then take their complement from frame zero through the end of the normalized picture. End the last interval in `null` rather than counting those frames yourself.

This example uses twelve seconds of source at 30 fps. Frames 90–104 are a reviewed hesitation. The closing statement (frames 240–359) is moved to the beginning.

```json
{"fps": 30, "keep": [[240, 360], [0, 90], [105, 240]]}
```

An interval may end in `null`, which runs it to the source's last frame on the plan's grid. The renderer counts the frames by decoding the source once with the same `fps` filter as the render, so the end is exact for a variable-frame-rate recording too. `[[0, null]]` keeps a whole video whose speed, background or color alone changes.

Ranges the user asked to remove, such as a trimmed opening or the passages a highlight leaves out, are also listed under `drop`, in the same frame form. The renderer ignores it. The checker uses it to tell speech removed on purpose from speech a filler cut lost. This plan trims the first five seconds and one hesitation, and keeps everything after:

```json
{"fps": 30, "keep": [[150, 300], [312, null]], "drop": [[0, 150]]}
```

Save the first example as `plan.json`. It produces 345 frames, or 11.5 seconds. Sources for the plan, media and source SRT must share the same time origin. When working from an approved cut, use its time coordinates. To regrade from camera originals, map the approved cut's intervals back through the earlier keep list first.

## Check the plan before rendering

```sh
python3 scripts/verify_plan.py words.json plan.json --edited words_edited.json
```

The checker prints the kept duration, the cut count, and any content word that a removed range overlaps by more than 50 ms, which is how a cut that ate a syllable's onset is caught without listening. With `--edited`, it also compares content characters between the two transcripts; an unequal count means the cut lost or invented speech. Words wholly inside a `drop` range are left out of both checks and reported as removed on purpose. A word straddling a drop boundary still fails, so move that boundary into the gap between two words. The checker also fails a drop range that overlaps kept footage. Exit status is nonzero when either check fails. Expect a first pass to fail this and to need repair at the reported timestamps.

## Render

```sh
python3 scripts/cut_video.py input.MOV plan.json clean.mp4
python3 scripts/cut_video.py input.MOV plan.json final.mp4 \
  --source-srt source.srt --burn-font /path/to/ChineseFont.ttc --font-index 1
```

Use `--edited-srt final-timeline.srt` in place of `--source-srt` when the cues already follow the final cut. Supplying an SRT writes an editable sidecar next to the MP4. Adding a font burns the same cues into the picture. Line breaks in the SRT control caption wrapping, and each line is centred on its visible characters. Review slow or crowded cues before rendering.

`--burn-font` accepts any TTF, OTF or TTC file, so a downloaded typeface such as Source Han Sans works the same way as a system font. Select the face with `--font-index` for a collection; this lists the faces and their index:

```sh
python3 -c "import sys; from PIL import ImageFont as F
for i in range(64):
  try: print(i, *F.truetype(sys.argv[1], 20, index=i).getname())
  except OSError: break" /path/to/Font.ttc
```

Before encoding, the renderer stops and names any caption character the font has no glyph for, since it would otherwise burn a placeholder box into the picture. Decorative typefaces often omit punctuation, digits or less common Han characters.

`--caption-style` chooses how burned-in cues look; it requires `--burn-font`. Every style keeps the same position, size and line limit.

| Style | Look |
| --- | --- |
| `box` (default) | White text on a translucent dark box |
| `white-box` | Dark text on a white box |
| `yellow-box` | Dark text on a solid yellow box |
| `outline` | White text with a black outline, no box |
| `yellow-outline` | Yellow text with a black outline, no box |
| `shadow` | White text with a thin outline and a soft drop shadow |

Boxed styles stay readable over any background. Outline and shadow styles cover less of the picture but depend on the stroke, so check them against bright clothing and backgrounds. To compare styles, render the same short temporary plan once per style and inspect the frames with the actual speaker.

Portrait cues sit below the face, sized from the frame width. A landscape frame puts them near its bottom edge and sizes them from its height, about 5% of it, so the 23-character line limit still fits.

`--speed` plays the whole delivered cut faster or slower, from 0.5 to 5, at the plan's frame rate. A fraction such as `4/3` is accepted. The voice keeps its pitch, and frames are dropped or repeated to hold the delivery rate. FFmpeg's `atempo` skips samples rather than blending them above 2, so a faster speed is split into equal stages of at most 2. Keep the plan and any `--source-srt` or `--edited-srt` on the normal-speed timeline; the renderer rescales the cues and writes the sidecar for the delivered speed. Omitting it, or passing 1, renders exactly as before.

```sh
python3 scripts/cut_video.py input.MOV plan.json fast.mp4 --speed 1.25 \
  --source-srt source.srt --burn-font /path/to/ChineseFont.ttc --font-index 1
```

The renderer splits chronological cuts into runs of at most 90 intervals, because FFmpeg's expression evaluator rejects a `select` with more than 100 `between()` terms and reports the size limit as `Cannot allocate memory`. A full-talk cleanup of a ten-minute recording commonly needs more, so keep the plan as one flat chronological list and let the renderer chunk it. Each run is encoded separately and joined, and every part is checked for its frame count. A part of one or two frames has no B-frames, so the join renumbers decode timestamps evenly across all parts; otherwise a constant-frame-rate transcode would repeat frames there.

The renderer targets square-pixel footage, such as phone recordings, screen recordings and camera files, and produces H.264/AAC SDR video in the displayed orientation and frame size. It uses the first audio track. A source without one gives a video-only MP4 and has no speech for the filler finder. A frame with an odd width or height loses its last column or row, because H.264 in 4:2:0 needs even sides; a recording of a selected screen area is the usual case. If an input needs a different audio track, HDR delivery, PQ tone mapping or a different layout, adapt the FFmpeg workflow to that source. To try two HLG exposures, render a short representative plan into separate preview files with `--hlg-strength 2.6` and `--hlg-strength 2.0`. The lower value gives a darker result. Use the approved setting for the final encode. Each render checks that the entire output decodes.

Scratch files go to a hidden `.cut-video-*` folder beside the output, kept on the same filesystem so the finished files can be hard-linked into place. Pass `--workdir <dir>` to move that work into the agent's own directory, which copies across filesystems instead of linking. The folder is removed on success or failure, but survives a killed process; report it for the user to remove rather than deleting inside their folders.

For a short hook, use a temporary plan containing just its spans and inspect the resulting first two seconds before the full export. Use the same intervals in the final plan. Reuse the original high-quality video and audio when revising an edit.

## Background

`--background` shrinks the picture into a rounded card with a soft shadow and fills the rest of the same-sized frame:

| Value | Background |
| --- | --- |
| `sunset`, `spring`, `ocean`, `dusk` | A built-in mesh gradient: orange to violet, green to yellow, blue, dark violet |
| `random` | One of those presets, printed on stderr |
| A colour, e.g. `'#efe9df'` or `white` | A solid colour |
| An image path | The image, scaled to cover the frame and centred. HEIC, the format of the macOS wallpapers in `/System/Library/Desktop Pictures`, is converted with `sips` |
| `blur` | The picture itself, blurred and darkened |

`--padding` is the margin around the card and `--radius` its corner radius, both as a percentage of the frame's short side (defaults 6 and 3.5, limits 25 and 20). Using the short side gives a portrait and a landscape frame the same margin. Burned-in captions are laid out on the card, so a long cue never runs past its edge, and the 23-character line limit holds at any padding.

```sh
python3 scripts/cut_video.py input.MOV plan.json framed.mp4 --background sunset \
  --source-srt source.srt --burn-font /path/to/ChineseFont.ttc --font-index 1
python3 scripts/cut_video.py input.MOV plan.json framed.mp4 \
  --background "/System/Library/Desktop Pictures/Sonoma.heic" --padding 10 --radius 6
```

A still background is drawn once per render as a layer with the shadow and a card-shaped hole, and laid over the padded picture, so it adds little encoding time. `blur` builds its background from each frame instead. Gradients carry faint grain, because a smooth 8-bit gradient bands after H.264 compression. Still layers are converted to the delivery's BT.709 colours explicitly; FFmpeg's default conversion would use BT.601 and shift them. Without `--background`, the picture fills the frame as before.

## Voice

`--voice` replaces the sound with the caption cues read aloud by Doubao Speech (豆包语音), using its streaming TTS endpoint `openspeech.bytedance.com/api/v3/tts/unidirectional`. The cues come from `--source-srt` or `--edited-srt` as usual, and a source without sound works the same way. Each cue's whole text is spoken, so when the plan cuts inside a cue, supply an `--edited-srt` whose text is exactly the kept speech; a remapped source cue would still carry the removed words, and a hook moved out of a cue would be spoken twice.

```sh
DOUBAO_API_KEY=... python3 scripts/cut_video.py input.MOV plan.json revoiced.mp4 \
  --edited-srt final-timeline.srt --voice zh_female_vv_uranus_bigtts
DOUBAO_API_KEY=... python3 scripts/cut_video.py screen.mov whole.json narrated.mp4 \
  --edited-srt narration.srt --voice zh_male_m191_uranus_bigtts --voice-rate 1.1 \
  --burn-font /path/to/ChineseFont.ttc --font-index 1
```

The voice ID chooses the service the request goes to: an ID containing `_uranus_` is a 2.0 voice on `seed-tts-2.0`, one starting `S_` is a cloned voice on `seed-icl-2.0`, and any other is a 1.0 voice on `seed-tts-1.0`. `DOUBAO_RESOURCE_ID` names the service outright, as a voice cloned on the 1.0 service (`seed-icl-1.0`) needs. A key reaches only the services enabled for it in the Volcengine console, so a voice outside them fails with HTTP 403 or `resource ID is mismatched with speaker related resource`, which is also the reply to a mistyped ID. The full list is the 音色列表 page of the [Doubao Speech documentation](https://www.volcengine.com/docs/6561). These 2.0 voices have been tried, and each also reads English:

| Voice ID | Voice |
| --- | --- |
| `zh_female_vv_uranus_bigtts` | Vivi 2.0, female |
| `zh_female_xiaohe_uranus_bigtts` | Female |
| `zh_male_m191_uranus_bigtts` | 云舟 2.0, male |
| `zh_male_taocheng_uranus_bigtts` | Male |

Each cue is one request. Its lines are joined into one sentence, and a cue without letters or digits, such as `♪`, stays silent. The returned speech, with its leading and trailing silence trimmed, starts on the cue's first frame. When it is longer than the cue, it runs on into the following pause until 0.2 seconds before the next cue, and the cue's end moves to where the voice stops, in the sidecar and the burned-in captions. A sentence that is still too long is requested again at a faster `speech_rate` and then compressed with `atempo` to fit exactly. The renderer prints cues spoken more than 1.25× faster than the requested pace, and stops before encoding when any would need more than 1.5×, listing their delivered times and text. Widen such a cue into the silence around it or split its text across two cues.

`--voice-rate` is the requested pace, from 0.5 to 2 times the voice's own. With `--speed`, the voice is generated for the delivered timeline at the voice rate times the speed, so it reads faster instead of being compressed afterwards. Doubao Speech reads from half to double speed, so a product outside that range is held to it: a sentence is then compressed only where it would not fit its cue, and a slow one is not stretched. The track is brought to -16 LUFS integrated, with a limiter holding sample peaks under -1.5 dBFS, and delivered as mono AAC. The recorded sound is dropped entirely, music and room sound included, because it still carries the old voice.

Four requests run at once, at two to three seconds each, so a ten-minute talk with 200 cues adds about three minutes, and every render requests them again. Preview a new voice on a short plan first. A failed connection, a stream that ends before its closing message, HTTP 429 and server errors are retried twice, and a request refused in the parallel pass, as by a key allowed fewer at once, is made again on its own. The request goes direct, or through `HTTPS_PROXY` when set, but not through the macOS system proxy, and uses the `certifi` certificate bundle when that package is installed.

## Languages

`--voice-language` names the language of the cues for the voice, sent as Doubao Speech's `explicit_language`. Without it a voice reads Chinese and English only, and a cue of bare digits such as `100%` is read in Chinese, even by an English voice; pass `en` for an English dub. Other text is not refused by the service: French, German or Dutch comes back read with English sounds, and Japanese, Korean, Russian, Arabic or Thai as no audio. The renderer therefore stops before any request when a cue has letters other than Chinese or English and no language is named. A code the service does not know is ignored the same way, so only these codes, each heard to work, are accepted:

| Code | Language | Code | Language |
| --- | --- | --- | --- |
| `zh-cn` | Chinese, with English mixed in | `en` | English |
| `ja` | Japanese | `ko` | Korean |
| `es-mx` | Spanish (Mexico) | `pt-br` | Portuguese (Brazil) |
| `fr` | French | `de` | German |
| `it` | Italian | `ru` | Russian |
| `id` | Indonesian | `vi` | Vietnamese |
| `th` | Thai | `ar` | Arabic |
| `hi` | Hindi | `tr` | Turkish |
| `nl` | Dutch | `pl` | Polish |
| `sv` | Swedish | `no` | Norwegian |
| `fi` | Finnish | `cs` | Czech |
| `hu` | Hungarian | `el` | Greek |
| `ro` | Romanian | `fil` | Filipino |

Each was tried with Vivi 2.0, and Japanese, Korean, French and Arabic with other 2.0 voices as well. `en` or `zh-cn` lets English or Chinese cues through that carry an accented name. Danish came back sounding German, and Ukrainian could not be told from Russian, so neither is offered. The English 2.0 voices, such as `en_male_tim_uranus_bigtts` and `en_female_dacey_uranus_bigtts`, read English with a native accent.

```sh
DOUBAO_API_KEY=... python3 scripts/cut_video.py input.MOV plan.json english.mp4 \
  --edited-srt english-cues.srt --voice en_male_tim_uranus_bigtts --voice-language en \
  --burn-font /System/Library/Fonts/HelveticaNeue.ttc --font-index 10
DOUBAO_API_KEY=... python3 scripts/cut_video.py input.MOV plan.json japanese.mp4 \
  --edited-srt japanese-cues.srt --voice zh_female_vv_uranus_bigtts --voice-language ja \
  --burn-font "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"
```

When a cue's lines are joined into one sentence, they join directly where Chinese or Japanese meets the break and with a space between words of other languages, so a word at the end of one line does not run into the next.

At the voice's own pace English runs about three words a second, and Chinese and Japanese about five characters, so a translation of Chinese speech is usually the longer to say. The fit is reported the same way as for any voice: hurried cues are listed and those beyond 1.5× refused. A Japanese voice can give a kanji word its Chinese reading, as it did 字幕 at the start of one sentence, so compare the transcript of a Japanese dub word by word.

A line of English or another language written with spaces fits up to about 46 characters at the smallest size the renderer accepts, fewer in capitals; 42 leaves margin. Fonts on macOS that carry each language:

| Language | Font | `--font-index` |
| --- | --- | --- |
| Latin, Cyrillic and Greek letters, including Vietnamese and Romanian | `/System/Library/Fonts/HelveticaNeue.ttc`, Medium | 10 |
| Japanese | `/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc`, Hiragino Sans | 0 |
| Korean | `/System/Library/Fonts/AppleSDGothicNeo.ttc`, Medium | 2 |
| Thai | `/System/Library/Fonts/ThonburiUI.ttc` | 0 |
| Arabic | `/System/Library/Fonts/GeezaPro.ttc` | 0 |
| Hindi | `/System/Library/Fonts/Kohinoor.ttc`, Kohinoor Devanagari Medium | 1 |
| Chinese with English, French or German | `/System/Library/Fonts/STHeiti Medium.ttc`, Simplified | 1 |

STHeiti lacks Korean and some Vietnamese and Romanian letters, and Hiragino draws shared kanji in Japanese forms. A bilingual cue needs one font with both scripts; `/System/Library/Fonts/Supplemental/Arial Unicode.ttf` covers most pairs. The glyph check names whatever a font lacks before encoding. A landscape caption strip holds three lines, so a bilingual cue there takes one line of each language.

Arabic and Hebrew run right to left, Arabic with joined letters, and the vowel signs of Thai and Hindi attach to their consonants. Pillow places them only through its Raqm layout, which loads the FriBiDi library when run; without it, Arabic is drawn unjoined and left to right, and Thai and Hindi signs sit on dotted circles. The renderer refuses to burn such cues when Raqm is unavailable. `python3 -c "from PIL import features; print(features.check('raqm'))"` reports it. On macOS with Homebrew, `brew install fribidi` and run the renderer as `DYLD_FALLBACK_LIBRARY_PATH=$(brew --prefix)/lib python3 scripts/cut_video.py …` so Pillow finds it. macOS drops the variable on its way through `/usr/bin/python3`, an `env` shebang or `sh -c`, so call a Homebrew or python.org `python3` directly. Otherwise deliver the SRT without burn-in, for the platform's own captions.
