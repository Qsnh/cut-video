"""Read, remap and draw prepared SubRip cues on the final frame grid."""
import re
from fractions import Fraction
from pathlib import Path


def read_srt(path, fps):
    def frame(code):
        match = re.fullmatch(r'(\d+):(\d{2}):(\d{2})[,.](\d{3})', code)
        if not match:
            raise ValueError(f"Invalid SRT time: {code}")
        h, m, s, ms = map(int, match.groups())
        return round((3600*h + 60*m + s + Fraction(ms, 1000)) * fps)

    result = []
    for block in re.split(r'\n[ \t]*\n', path.read_text(encoding='utf-8-sig').strip()):
        _, times, text = block.split('\n', 2)
        start, end = map(frame, times.strip().split(' --> '))
        if end <= start or (result and result[-1][1] > start):
            raise ValueError(f"Empty or overlapping subtitle: {times}")
        result.append((start, end, text))
    return result


def remap(cues, spans):
    result = []
    offset = 0
    for start, end in spans:
        for left, right, text in cues:
            a, b = max(left, start), min(right, end)
            if a >= b:
                continue
            at, stop = offset + a-start, offset + b-start
            if result and result[-1][1:] == (at, text):
                result[-1] = (result[-1][0], stop, text)
            else:
                result.append((at, stop, text))
        offset += end-start
    return result


def write_srt(path, cues, fps):
    def stamp(frame):
        ms = round(frame*1000/fps)
        return f'{ms//3600000:02d}:{ms//60000%60:02d}:{ms//1000%60:02d},{ms%1000:03d}'
    path.write_text('\n\n'.join(
        f'{i}\n{stamp(a)} --> {stamp(b)}\n{text}'
        for i, (a, b, text) in enumerate(cues, 1))+'\n', encoding='utf-8')


def overlays(folder, cues, first, last, fps, font_path, font_index, width, height):
    from PIL import Image, ImageDraw, ImageFont

    folder.mkdir()
    strip = max(12, round(height*.15))
    listing = ['ffconcat version 1.0']
    position = first
    index = 0

    def card(text, duration):
        nonlocal index
        if duration <= 0:
            return
        image = Image.new('RGBA', (width, strip))
        if text:
            d = ImageDraw.Draw(image)
            for size in range(max(12, round(width*.048)), 6, -1):
                font = ImageFont.truetype(str(font_path), size, index=font_index)
                b = d.multiline_textbbox((0, 0), text, font=font, spacing=4, align='center')
                w, h = b[2]-b[0], b[3]-b[1]
                if w < width*.82 and h < strip*.84:
                    break
            if size < max(7, round(width*.035)):
                raise ValueError(f'Split the cue for mobile readability: {text}')
            x, y = round((width-w)/2-width*.022), (strip-h)//2
            px, py = max(2, size//3), max(2, size//5)
            d.rounded_rectangle((x-px, y-py, x+w+px, y+h+py), radius=py,
                                fill=(16, 18, 20, 205))
            d.multiline_text((x-b[0], y-b[1]), text, font=font, fill='white',
                             spacing=4, align='center')
        name = f'cue{index}.png'
        image.save(folder/name)
        listing.extend([f"file '{name}'", f'option framerate {fps}',
                        f'duration {float(duration/fps):.9f}'])
        index += 1

    for start, end, text in cues:
        a, b = max(first, start), min(last, end)
        if a < b:
            card('', a-position)
            card(text, b-a)
            position = b
    card('', last-position)
    listing.extend([f"file 'cue{index-1}.png'", f'option framerate {fps}'])
    manifest = folder/'captions.ffconcat'
    manifest.write_text('\n'.join(listing)+'\n')
    return manifest
