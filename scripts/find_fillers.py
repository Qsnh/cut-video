#!/usr/bin/env python3
"""Locate possible spoken hesitations with a local Whisper model; retain word context.

Each quiet-separated chunk is decoded once and saved as its own file, so an interrupted
long recording resumes instead of restarting. A chunk whose decode collapses into a
repeated token is re-decoded before its words reach the candidate list.
"""
import argparse
import itertools
import json
import re
import subprocess
from pathlib import Path

import numpy as np


def chunks(audio):
    rate = 16000
    block = rate // 50
    frames = audio[:len(audio)//block*block].reshape(-1, block)
    rms = np.sqrt((frames**2).mean(axis=1))
    changes = np.diff(np.r_[False, rms < .012, False].astype(int))
    rests = [(int(a+b)*block//2, int(b-a)) for a, b in zip(np.where(changes>0)[0],
                                                          np.where(changes<0)[0]) if b-a >= 8]
    start = 0
    while start < len(audio):
        end = min(start+26*rate, len(audio))
        if end < len(audio):
            choices = [(n, at) for at, n in rests if start+18*rate <= at <= start+27*rate]
            if choices:
                end = max(choices)[1]
        yield start, audio[start:end]
        start = end


def trim(text):
    return ''.join(c for c in text if c not in '，。？！、,.?!﹑')


def collapsed(words, ratio):
    """True when a decode looped, which fabricates repeated speech in silence.

    Whisper flags its own loops through the segment compression ratio, which sits near
    1.5 for ordinary speech and above 2.4 when a decode collapses. A phrase repeated
    twice is normal delivery, so it counts only on a decode that already looks dense.
    """
    if ratio and ratio > 2.4:
        return True
    tokens = [trim(w['text']) or w['text'] for w in words]
    if max((len(list(group)) for _, group in itertools.groupby(tokens)), default=0) >= 4:
        return True
    if not ratio or ratio < 2.0:
        return False
    for size in (2, 3, 4):
        for i in range(len(tokens)-2*size+1):
            if tokens[i:i+size] == tokens[i+size:i+2*size]:
                return True
    return False


def decode(model, clip, language, prompt, beam):
    result = model.transcribe(clip, language=language, fp16=False, beam_size=beam,
                              word_timestamps=True, condition_on_previous_text=False,
                              initial_prompt=prompt,
                              # Lets Whisper replace a decode that fails its own quality check.
                              temperature=(0.0, .2, .4, .6))
    words = []
    for segment in result['segments']:
        for w in segment['words']:
            words.append(dict(text=w['word'], start=max(0, w['start']), end=max(0, w['end']),
                              probability=round(w['probability'], 3)))
    ratio = max((s.get('compression_ratio') or 0 for s in result['segments']), default=0)
    return words, collapsed(words, ratio)


def read_chunk(model, clip, language, prompt, index):
    words, looped = decode(model, clip, language, prompt, 1)
    if looped or not words:
        retry, retry_looped = decode(model, clip, language, prompt, 5)
        # Prefer a decode that does not loop, then the longer transcript.
        if (retry_looped, len(retry)) < (looped, len(words)):
            words, looped = retry, retry_looped
        if looped:
            print(f'chunk {index}: decode still loops, review this range by ear')
    return words


def main():
    import torch
    import whisper

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path)
    p.add_argument('output', type=Path)
    p.add_argument('--model', type=Path, required=True, help='Local Whisper .pt checkpoint')
    p.add_argument('--language', choices=['zh', 'en'], default='zh')
    p.add_argument('--terms', default='', help='Names and technical terms spoken in this recording')
    p.add_argument('--threads', type=int, default=4)
    p.add_argument('--parts', type=Path,
                   help='Chunk files for resuming, by default <output>.parts')
    args = p.parse_args()
    if not args.model.is_file() or args.output.exists():
        p.error('Supply a local Whisper checkpoint and a new output name.')
    torch.set_num_threads(args.threads)
    model = whisper.load_model(str(args.model), device='cpu')
    raw = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(args.source),
                                  '-map', '0:a:0', '-af', 'aresample=16000:async=1:first_pts=0',
                                  '-ac', '1', '-f', 's16le', '-'])
    audio = np.frombuffer(raw, '<i2').astype('float32')/32768
    if not len(audio):
        p.error('The input speech track is empty.')
    chinese = args.language == 'zh'
    prompt = ('嗯，呃，啊，我觉得。' if chinese else 'Um, uh, I think.') + ' ' + args.terms
    pattern = re.compile(r'[嗯呃啊噢哦唔]' if chinese else r'\b(?:umm*|uhh*|ermm*)\b', re.I)

    # Chunk boundaries follow the audio, so a saved chunk keeps its index between runs.
    parts = args.parts or args.output.with_suffix('.parts')
    parts.mkdir(parents=True, exist_ok=True)
    signature = dict(model=args.model.name, language=args.language,
                     samples=len(audio), prefix=args.terms)
    meta = parts/'meta.json'
    if meta.exists() and json.loads(meta.read_text()) != signature:
        p.error(f'{parts} holds chunks from a different run; choose another --parts folder.')
    meta.write_text(json.dumps(signature))

    words, resumed = [], 0
    for index, (offset, clip) in enumerate(chunks(audio)):
        part = parts/f'{index:03d}.json'
        if part.exists():
            found = json.loads(part.read_text())
            resumed += 1
        else:
            found = read_chunk(model, clip, args.language, prompt, index)
            part.write_text(json.dumps(found, ensure_ascii=False))
        for w in found:
            clip_seconds = len(clip)/16000
            start = min(clip_seconds, w['start']) + offset/16000
            end = min(clip_seconds, w['end']) + offset/16000
            words.append(dict(text=w['text'], start=round(start, 3), end=round(end, 3),
                              probability=w['probability']))
    if resumed:
        print(f'reused {resumed} saved chunks from {parts}')

    candidates = []
    for i, w in enumerate(words):
        if pattern.search(w['text']):
            candidates.append(dict(word_index=i, start=w['start'], end=w['end'],
                                   before=''.join(v['text'] for v in words[max(0,i-4):i]),
                                   token=w['text'], after=''.join(v['text'] for v in words[i+1:i+5])))
    result = dict(time_unit='source seconds', words=words, candidates=candidates)
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print(f'{len(candidates)} candidates for review in {args.output}')
    print(f'chunks kept in {parts}; delete that folder once the edit is approved')


if __name__ == '__main__':
    main()
