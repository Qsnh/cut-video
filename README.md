# cut-video · 视频剪辑 Skill

给 AI 助手（Claude Code、Codex 等）用的一个 Skill。把录好的视频交给它，口播、带解说的录屏、教程、实拍片段都行：剪掉「嗯、啊、呃」、掐头去尾、加同步字幕、倍速、加背景，这些可以任意组合，一次做完。输出可以直接发抖音 / TikTok 的 MP4。

视频全程在本机处理，不会上传。

## 能做什么

- **去语气词**：只要视频里有人说话（口播、带解说的录屏、教程），都能保留完整内容，只剪掉「嗯、呃、啊」、um、uh 和多余停顿。剪完会重新识别一遍并核对字数，确认没误删内容。
- **掐头去尾、删片段**：按你说的时间或画面描述来剪（去掉前 5 秒、只留某一段、删掉中间卡住的一段），可以和去语气词同时做。没有声音的视频（比如纯录屏）会输出无声 MP4；框选区域录屏常见的奇数宽高会自动处理。
- **加字幕**：生成跟剪辑后语音对齐的字幕，输出 SRT 文件，也可以直接烧进画面（竖屏放在人脸下方，横屏放在画面底部）。烧录字幕有 6 种样式可选：半透明深色底框（默认）、白底黑字、黄底黑字、白字黑描边、黄字黑描边、白字投影；字体也可以换成你自己的，字体里缺字时会在渲染前提示。
- **修正 iPhone 过曝**：iPhone 拍的 HDR（HLG）视频看起来发白、过亮，可以转成正常亮度的 SDR，亮度可调。
- **加背景**：把画面缩成带阴影的圆角卡片，放在背景上（类似 Screen Studio），竖屏横屏都行，输出尺寸不变。背景可以是 4 种内置渐变（sunset、spring、ocean、dusk，也可以随机挑）、纯色、你自己的图片（包括 macOS 自带的 HEIC 壁纸），或者视频自身的模糊画面；边距和圆角可调。
- **倍速**：整条视频按 0.5–5 倍加速或放慢，声音保持原来的音调，字幕时间同步缩放。2 倍以上更像快进，适合展示过程，字幕会一闪而过。
- **开头放钩子**：把你指定的金句或观点挪到视频开头。
- **剪精华版**：你要求时才剪，默认保留整段内容。

## 适合谁

✅ 适合

- 单人、单机位的口播、讲解、知识分享视频
- 录屏、教程、产品演示、游戏录像、实拍片段等单条视频
- 去语气词需要说中文或英文；其他剪辑不限语言
- 手机录的视频，尤其是 iPhone

❌ 不适合

- 多机位切换、多条素材拼接、插 B-roll、配乐、转场、特效：它一次处理一条视频，不是多轨剪辑软件
- 杜比视界 / HDR10（PQ）素材，或者需要输出 HDR 视频：目前只输出 H.264 / AAC 的 SDR MP4
- 中英文以外语言的去语气词：语气词识别只支持这两种，不影响其他剪辑

## 需要准备

| 用途 | 依赖 |
| --- | --- |
| 必需 | Python 3、NumPy、FFmpeg 4.4 或更新版本（含 ffprobe） |
| 找语气词 | openai-whisper、PyTorch、本地 Whisper 模型（中文建议 `small` 或更大） |
| 字幕烧进画面、加背景 | Pillow、一款含中文字形的字体（macOS 自带 `STHeiti Medium.ttc`，也可以换成任意 TTF / OTF / TTC 字体） |

macOS 上可以这样装：

```sh
brew install ffmpeg
pip3 install numpy pillow openai-whisper
# 下载 Whisper 模型，保存在 ~/.cache/whisper/small.pt
python3 -c "import whisper; whisper.load_model('small')"
```

语音识别在 CPU 上跑，长视频需要等一阵；中途中断的话，再次运行会从断点继续。

## 安装

把仓库克隆到你所用 AI 助手的 skills 目录：

```sh
# Claude Code
git clone https://github.com/Qsnh/cut-video.git ~/.claude/skills/cut-talking-video

# Codex
git clone https://github.com/Qsnh/cut-video.git ~/.codex/skills/cut-talking-video
```

## 使用

直接跟 AI 助手说你想要的效果，例如：

> 帮我剪一下 ~/Movies/IMG_0001.MOV，保留完整内容，去掉语气词，加同步中文字幕。

> 字幕换成黄字黑描边。

> 字幕用 ~/Downloads/SourceHanSansSC-Bold.otf 这个字体。

> 这段是 iPhone 拍的，画面太亮了，压一下曝光。

> 整条视频调成 1.25 倍速。

> 给视频加个背景，用日落渐变。

> 背景换成 /System/Library/Desktop Pictures/Sonoma.heic，边距大一点。

> 把「90% 的人都做错了」这句挪到开头。

> 这段录屏去掉前 5 秒和语气词，整体 1.5 倍速，再加个海蓝背景。

视频里有人说话时，它会先识别语音、找出可能的语气词，逐个核对后再剪辑；你要的掐头去尾、倍速、背景等会合进同一次渲染。最后交付：

- 剪好的 MP4（每次都是新文件，原视频不动）
- 对应的 SRT 字幕文件（要求加字幕时）

## 手动运行脚本

不通过 AI 助手也能直接用 `scripts/` 里的脚本：

| 脚本 | 作用 |
| --- | --- |
| `find_fillers.py` | 用本地 Whisper 转写，列出语气词候选 |
| `verify_plan.py` | 渲染前检查剪辑方案有没有切到正常说话的字 |
| `cut_video.py` | 按剪辑方案渲染视频，可选重排字幕、烧录字幕（`--caption-style` 选样式，`--burn-font` 选字体）、倍速（`--speed`）、加背景（`--background`）、HDR 转 SDR |

命令和剪辑方案格式见 [references/render.md](references/render.md)。
