#!/usr/bin/env python3
"""Render reviewed source-frame intervals in playback order."""
import argparse
import errno
import json
import math
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import wave
from fractions import Fraction
from pathlib import Path

import numpy as np
from captions import STYLES, missing_glyphs, overlays, read_srt, remap, write_srt
from color import grade


def probe(path):
    raw = subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(path)])
    return json.loads(raw)['streams']


def ff(work, *args):
    subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-n',
                    *map(str, args)], cwd=work, check=True)


def publish(src, dest):
    """Hard-link within one filesystem, copy when the work directory is elsewhere."""
    try:
        os.link(src, dest)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        shutil.copy2(src, dest)


def plan(path):
    spec = json.loads(path.read_text())
    fps = Fraction(str(spec['fps']))
    if fps <= 0:
        raise ValueError('fps must be positive.')
    spans = []
    for left, right in spec['keep']:
        if type(left) is not int or type(right) is not int or not 0 <= left < right:
            raise ValueError('Each keep interval must contain two ordered, nonnegative frame indices.')
        if spans and spans[-1][1] == left:
            spans[-1] = (spans[-1][0], right)
        else:
            spans.append((left, right))
    if not spans:
        raise ValueError('The edit plan must retain some footage.')
    return fps, spans


def make_audio(work, source, spans, fps, channels):
    rate = 48000
    ff(work, '-i', source, '-map', '0:a:0', '-af', 'aresample=48000:async=1:first_pts=0',
       '-ac', channels, '-c:a', 'pcm_s16le', 'input.wav')
    with wave.open(str(work/'input.wav')) as inp, wave.open(str(work/'edit.wav'), 'wb') as out:
        out.setparams((channels, 2, rate, 0, 'NONE', 'not compressed'))
        cursor = 0
        for left, right in spans:
            size = round((cursor+right-left)*rate/fps)-round(cursor*rate/fps)
            inp.setpos(min(round(left*rate/fps), inp.getnframes()))
            fade = min(240, size//2)
            for offset in range(0, size, rate*5):
                count = min(rate*5, size-offset)
                raw = inp.readframes(count).ljust(count*channels*2, b'\0')
                if fade and (offset < fade or offset+count > size-fade):
                    idx = np.arange(offset, offset+count)
                    gain = np.clip(np.minimum(idx, size-1-idx)/fade, 0, 1)
                    pcm = np.frombuffer(raw, dtype='<i2').reshape(-1, channels)
                    raw = np.rint(pcm*gain[:, None]).astype('<i2').tobytes()
                out.writeframesraw(raw)
            cursor += right-left


def render(args, work):
    fps, spans = plan(args.plan)
    total = sum(b-a for a, b in spans)
    streams = probe(args.source)
    video = next(s for s in streams if s['codec_type'] == 'video' and not s['disposition']['attached_pic'])
    audio = next(s for s in streams if s['codec_type'] == 'audio')
    width, height = video['width'], video['height']
    rotation = next((d['rotation'] for d in video.get('side_data_list', []) if 'rotation' in d), 0)
    if round(rotation/90) % 2:
        width, height = height, width
    color_filter = grade(video, work, args.hlg_strength)
    cues = []
    if args.source_srt:
        cues = remap(read_srt(args.source_srt, fps), spans)
    if args.edited_srt:
        cues = read_srt(args.edited_srt, fps)
        if cues and cues[-1][1] > total:
            raise ValueError('The edited SRT extends beyond the final frame.')
    if args.burn_font and not cues:
        raise ValueError('Burn-in requires caption cues on the retained footage.')
    if args.burn_font:
        missing = missing_glyphs(args.burn_font, args.font_index, cues)
        if missing:
            raise ValueError(f"{args.burn_font.name} has no glyph for {''.join(missing)}; "
                             'choose a font that covers every caption character.')
    if cues:
        write_srt(work/'edit.srt', cues, fps)

    # Each chronological run needs only one decoder. A run is chunked because FFmpeg's
    # expression evaluator rejects a select with more than 100 between() terms, which
    # an ordinary full-talk cleanup exceeds well before a hundred filler cuts.
    runs = []
    for span in spans:
        if not runs or span[0] < runs[-1][-1][1]:
            runs.append([])
        runs[-1].append(span)
    limit = 90
    runs = [chunk for run in runs for chunk in
            (run[i:i+limit] for i in range(0, len(run), limit))]
    cursor = 0
    listing = ['ffconcat version 1.0']
    for i, run in enumerate(runs):
        length = sum(b-a for a, b in run)
        inputs = ['-i', args.source]
        select = '+'.join(f'between(n,{a},{b-1})' for a, b in run)
        graph = (f"[0:{video['index']}]fps={fps}:start_time=0,select='{select}',"
                 f'setpts=N/(({fps})*TB),{color_filter}')
        if args.burn_font:
            manifest = overlays(work/f'cards{i}', cues, cursor, cursor+length, fps,
                                args.burn_font, args.font_index, width, height,
                                args.caption_style or 'box')
            inputs += ['-f', 'concat', '-safe', '0', '-i', manifest]
            graph += ('[pic];[1:v]format=rgba[txt];'
                      '[pic][txt]overlay=0:main_h*0.695:shortest=1')
        graph = graph+'[out]'
        graph_file = work/f'filter{i}.txt'
        graph_file.write_text(graph)
        part = f'part{i}.mp4'
        # FFmpeg 8+ dropped -filter_complex_script; the inline graph works on every version.
        ff(work, *inputs, '-filter_complex', graph, '-map', '[out]',
           '-frames:v', length, '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '19',
           '-pix_fmt', 'yuv420p', '-color_primaries', 'bt709', '-color_trc', 'bt709',
           '-colorspace', 'bt709', '-map_metadata', '-1', part)
        if int(probe(work/part)[0]['nb_frames']) != length:
            raise ValueError(f'Run {i+1} produced fewer than {length} frames. Check source bounds.')
        listing.extend([f"file '{part}'", f'duration {float(length/fps):.9f}'])
        cursor += length
    (work/'join.ffconcat').write_text('\n'.join(listing)+'\n')
    make_audio(work, args.source, spans, fps, min(audio['channels'], 2))
    ff(work, '-f', 'concat', '-safe', '0', '-i', 'join.ffconcat', '-i', 'edit.wav',
       '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
       '-movflags', '+faststart', '-map_metadata', '-1', 'edit.mp4')
    v, a = probe(work/'edit.mp4')
    if int(v['nb_frames']) != total or abs(float(a['duration'])-total/float(fps)) > max(.025, 1/float(fps)):
        raise ValueError('The output does not match the planned picture or audio duration.')
    ff(work, '-xerror', '-i', 'edit.mp4', '-map', '0:v:0', '-map', '0:a:0', '-f', 'null', '-')
    return bool(cues)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('plan', type=Path)
    parser.add_argument('output', type=Path)
    sub = parser.add_mutually_exclusive_group()
    sub.add_argument('--source-srt', type=Path, help='Retime cues from this source timeline')
    sub.add_argument('--edited-srt', type=Path, help='Use cues already aligned to final speech')
    parser.add_argument('--burn-font', type=Path, help='Burn captions using this TTF, OTF or TTC')
    parser.add_argument('--font-index', type=int, default=0)
    parser.add_argument('--caption-style', choices=list(STYLES),
                        help='Burned-in caption look (default box)')
    parser.add_argument('--hlg-strength', type=float, help='HLG highlight curve gain (default 2.6)')
    parser.add_argument('--workdir', type=Path,
                        help='Scratch space, by default a hidden folder beside the output')
    args = parser.parse_args()
    args.source = args.source.resolve(strict=True)
    if args.hlg_strength is not None and not (math.isfinite(args.hlg_strength) and args.hlg_strength > 0):
        parser.error('HLG strength must be positive and finite.')
    if args.caption_style and not args.burn_font:
        parser.error('A caption style needs --burn-font.')
    out = args.output.absolute()
    srt = out.with_suffix('.srt')
    if out.suffix.lower() != '.mp4' or out.exists() or ((args.source_srt or args.edited_srt) and srt.exists()):
        parser.error('Choose a fresh .mp4 output name and sidecar name.')
    parent = (args.workdir or out.parent).absolute()
    parent.mkdir(parents=True, exist_ok=True)
    # Without a handler, a terminated render leaves its scratch folder and cards behind.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    with tempfile.TemporaryDirectory(prefix='.talk-edit-', dir=parent) as tmp:
        work = Path(tmp)
        has_cues = render(args, work)
        if has_cues:
            publish(work/'edit.srt', srt)
        try:
            publish(work/'edit.mp4', out)
        except OSError:
            if has_cues:
                srt.unlink()
            raise
    print(out)
    if has_cues:
        print(srt)


if __name__ == '__main__':
    main()
