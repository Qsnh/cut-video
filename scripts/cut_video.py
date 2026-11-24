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
from captions import STYLES, missing_glyphs, overlays, read_srt, remap, retime, write_srt
from color import grade


def probe(path):
    raw = subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(path)])
    return json.loads(raw)['streams']


def decode_lead(path, fps):
    """Frames by which a part's first decode timestamp precedes its first picture."""
    raw = subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                                   '-read_intervals', '%+#1', '-show_entries',
                                   'packet=pts_time,dts_time', '-of', 'json', str(path)])
    packet = json.loads(raw)['packets'][0]
    return round((float(packet['pts_time'])-float(packet['dts_time']))*fps)


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
    speed = args.speed or 1
    delivered = round(total/speed)
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
    if cues and speed != 1:
        cues = retime(cues, speed)
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
    lead = 0
    listing = ['ffconcat version 1.0']
    for i, run in enumerate(runs):
        # A run's place on the delivered timeline is rounded from its unscaled place,
        # so the parts add up to the delivered total at any speed.
        length = sum(b-a for a, b in run)
        first, last = round(cursor/speed), round((cursor+length)/speed)
        count = last-first
        cursor += length
        if not count:
            continue
        inputs = ['-i', args.source]
        select = '+'.join(f'between(n,{a},{b-1})' for a, b in run)
        graph = f"[0:{video['index']}]fps={fps}:start_time=0,select='{select}',"
        if speed == 1:
            graph += f'setpts=N/(({fps})*TB),'
        else:
            # Resampling to the delivery rate can round a run one frame past its last
            # source frame, so clones of that frame covering two delivered frames pad
            # the end before -frames:v.
            pad = math.ceil(2*speed)+2
            graph += f'tpad=stop_mode=clone:stop={pad},setpts=N/(({fps*speed})*TB),fps={fps},'
        graph += color_filter
        if args.burn_font:
            manifest = overlays(work/f'cards{i}', cues, first, last, fps,
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
           '-frames:v', count, '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '19',
           '-pix_fmt', 'yuv420p', '-color_primaries', 'bt709', '-color_trc', 'bt709',
           '-colorspace', 'bt709', '-map_metadata', '-1', part)
        if int(probe(work/part)[0]['nb_frames']) != count:
            raise ValueError(f'Run {i+1} produced fewer than {count} frames. Check source bounds.')
        lead = max(lead, decode_lead(work/part, fps))
        listing.extend([f"file '{part}'", f'duration {float(count/fps):.9f}'])
    (work/'join.ffconcat').write_text('\n'.join(listing)+'\n')
    make_audio(work, args.source, spans, fps, min(audio['channels'], 2))
    tempo = []
    if speed != 1:
        # atempo keeps the voice's pitch. Above 2 it skips samples instead of blending
        # them, so a larger change is shared by equal stages of at most 2. Padding and
        # trimming pin the length to the picture.
        stages = max(1, math.ceil(math.log2(speed)))
        chain = ','.join([f'atempo={float(speed)**(1/stages)}']*stages)
        tempo = ['-af', f'{chain},apad,atrim=end_sample={round(delivered*48000/fps)}']
    # A part of one or two frames has no B-frames, so its decode timestamps start with its
    # pictures rather than two frames ahead like a longer part's. The join keeps each part's
    # offset, and the jump stretches one frame's duration until a constant-rate decoder
    # repeats frames. Renumbering every packet behind the largest lead spaces them evenly;
    # setts would also rewrite the picture times unless pts is given.
    ff(work, '-f', 'concat', '-safe', '0', '-i', 'join.ffconcat', '-i', 'edit.wav',
       '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy',
       '-bsf:v', f'setts=pts=PTS:dts=round((N-{lead})/(({fps})*TB))', *tempo, '-c:a', 'aac', '-b:a', '192k',
       '-movflags', '+faststart', '-map_metadata', '-1', 'edit.mp4')
    v, a = probe(work/'edit.mp4')
    if int(v['nb_frames']) != delivered or abs(float(a['duration'])-delivered/float(fps)) > max(.025, 1/float(fps)):
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
    parser.add_argument('--speed', type=Fraction,
                        help='Playback speed of the delivered cut, 0.5 to 5 (default 1)')
    parser.add_argument('--workdir', type=Path,
                        help='Scratch space, by default a hidden folder beside the output')
    args = parser.parse_args()
    args.source = args.source.resolve(strict=True)
    if args.hlg_strength is not None and not (math.isfinite(args.hlg_strength) and args.hlg_strength > 0):
        parser.error('HLG strength must be positive and finite.')
    if args.speed is not None and not Fraction(1, 2) <= args.speed <= 5:
        parser.error('Speed must be between 0.5 and 5.')
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
