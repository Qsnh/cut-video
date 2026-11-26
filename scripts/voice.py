"""Speak caption cues in a Doubao voice, each from its cue's start on the delivered cut."""
import base64
import json
import math
import os
import ssl
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPException
from urllib.error import HTTPError
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener, getproxies_environment

import numpy as np

URL = 'https://openspeech.bytedance.com/api/v3/tts/unidirectional'
RATE = 48000
# A voice may run on into the silence after its cue, stopping this far short of the next.
BREATH = .2
# Doubao speaks near -22 LUFS. The track is raised to a usual spoken-word level, and a
# limiter keeps headroom for the AAC encode.
LOUDNESS, PEAK = -16, -1.5
# Beyond this much faster than its requested pace, speech stops being easy to follow.
HURRY = 1.5
RAW = ['-f', 'f32le', '-ar', str(RATE), '-ac', '1']
# Requests in flight at once. A key allowed fewer gets its refused ones again in turn.
WORKERS = 4


def resource(speaker):
    """The service behind a voice ID: a cloned voice, a 2.0 voice or a 1.0 voice."""
    # A voice cloned on the 1.0 service, seed-icl-1.0, can only be named outright.
    if os.environ.get('DOUBAO_RESOURCE_ID'):
        return os.environ['DOUBAO_RESOURCE_ID']
    if speaker.startswith('S_'):
        return 'seed-icl-2.0'
    return 'seed-tts-2.0' if '_uranus_' in speaker else 'seed-tts-1.0'


def opener():
    # Proxies are taken from the environment only, as curl takes them. urllib would also
    # read the macOS system proxy, which can be a local tool that re-signs TLS.
    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context = ssl.create_default_context()
    return build_opener(ProxyHandler(getproxies_environment()), HTTPSHandler(context=context))


def request(text, speaker, rate):
    """MP3 bytes for the text. speech_rate runs from -50 (half speed) to 100 (double)."""
    body = {'user': {'uid': 'cut-video'}, 'req_params': {
        'text': text, 'speaker': speaker,
        'audio_params': {'format': 'mp3', 'sample_rate': RATE, 'speech_rate': round((rate-1)*100)}}}
    headers = {'Content-Type': 'application/json', 'X-Api-Key': os.environ['DOUBAO_API_KEY'],
               'X-Api-Resource-Id': resource(speaker)}
    # A voice ID the key's services do not include is reported as a resource mismatch.
    where = f'voice {speaker} on {resource(speaker)}'
    for attempt in range(3):
        audio, done = bytearray(), False
        headers['X-Api-Request-Id'] = str(uuid.uuid4())
        try:
            with opener().open(Request(URL, json.dumps(body).encode(), headers), timeout=60) as reply:
                for line in reply:
                    if not line.strip():
                        continue
                    message = json.loads(line)
                    code = message.get('code', 0)
                    if code == 20000000:
                        done = True
                    elif code:
                        raise RuntimeError(f"Doubao TTS error {code} for {where}: "
                                           f"{message.get('message')} (text: {text})")
                    if message.get('data'):
                        audio += base64.b64decode(message['data'])
        except HTTPError as exc:
            # A busy or failing service is asked again. The body of any other refusal
            # carries its reason, such as a wrong key or a voice the key cannot use.
            if attempt == 2 or exc.code != 429 and exc.code < 500:
                raise RuntimeError(f'Doubao TTS HTTP {exc.code} for {where}: '
                                   f'{exc.read().decode(errors="replace")}') from None
        except (OSError, HTTPException, json.JSONDecodeError):
            if attempt == 2:
                raise
        else:
            # Only the closing message shows that the stream was not cut short.
            if done and audio:
                return bytes(audio)
            if attempt == 2:
                raise RuntimeError(f'Doubao TTS returned {"no" if done else "incomplete"} '
                                   f'audio for {where}: {text}')
        time.sleep(2**attempt)


def pipe(data, *args):
    """What FFmpeg makes of data on its standard input, as mono float samples at RATE."""
    raw = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', *args, *RAW, '-'],
                         input=data, capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).copy()


def synthesize(text, speaker, rate):
    """Mono samples of the spoken text with the silence around it trimmed."""
    sound = pipe(request(text, speaker, rate), '-i', '-')
    loud = np.flatnonzero(np.abs(sound) > 10**(-45/20))
    if not loud.size:
        raise RuntimeError(f'Doubao TTS returned silence for: {text}')
    return sound[max(0, loud[0]-int(.03*RATE)):loud[-1]+int(.06*RATE)]


def tempo(sound, factor, size):
    """The sound played factor times faster at the same pitch, trimmed or padded to size."""
    # atempo skips samples instead of blending them above 2, so stages share the change.
    stages = max(1, math.ceil(math.log2(factor)))
    fast = pipe(sound.tobytes(), *RAW, '-i', '-', '-af',
                ','.join([f'atempo={factor**(1/stages)}']*stages))[:size]
    return np.concatenate([fast, np.zeros(size-len(fast), np.float32)])


def level(sound):
    """The speech raised to LOUDNESS, with its few louder peaks held under PEAK."""
    report = subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', *RAW, '-i', '-',
                             '-af', 'loudnorm=print_format=json', '-f', 'null', '-'],
                            input=sound.tobytes(), capture_output=True, check=True).stderr.decode()
    stats = json.loads(report[report.rindex('{'):report.rindex('}')+1])
    gain = LOUDNESS-float(stats['input_i'])
    # Speech too short to measure is left as spoken.
    if not math.isfinite(gain):
        return sound
    chain = f'volume={gain:.2f}dB'
    if float(stats['input_tp'])+gain > PEAK:
        chain += f',alimiter=limit={10**(PEAK/20):.4f}:level=false:attack=5:release=50'
    louder = pipe(sound.tobytes(), *RAW, '-i', '-', '-af', chain)[:len(sound)]
    return np.concatenate([louder, np.zeros(len(sound)-len(louder), np.float32)])


def spoken(text):
    """A cue's lines as one phrase, or '' when nothing in it can be read aloud."""
    phrase = ''
    for line in filter(None, (line.strip() for line in text.split('\n'))):
        # A caption line break sits inside a phrase, so Chinese lines join directly.
        gap = ' ' if phrase and phrase[-1].isascii() and line[0].isascii() else ''
        phrase += gap+line
    return phrase if any(c.isalnum() for c in phrase) else ''


def track(cues, fps, frames, speaker, pace, path):
    """Write the cues spoken in this voice as a mono WAV as long as the delivered cut.

    Cues are on the delivered frame grid and pace is the requested speaking rate, 1 being
    the voice's own. Each cue is spoken from its start. A voice longer than its cue runs on
    into the silence before the next cue, and the cue is extended to cover it. One that
    still does not fit is requested faster, then compressed to fit. Returns the cues with
    their new ends and, for each cue that had to be hurried, its start frame and how much
    faster than the requested pace it is spoken.
    """
    # Doubao reads at half to double speed; a faster pace is reached by compression.
    rate = min(2, max(.5, pace))
    total = round(frames*RATE/fps)
    voice = np.zeros(total, np.float32)
    phrases = [spoken(text) for _, _, text in cues]

    def first(phrase):
        try:
            return synthesize(phrase, speaker, rate) if phrase else None
        except Exception:
            return None

    with ThreadPoolExecutor(WORKERS) as pool:
        sounds = list(pool.map(first, phrases))
    result, faster, rushed = [], [], []
    for i, ((a, b, text), phrase, sound) in enumerate(zip(cues, phrases, sounds)):
        if not phrase:
            result.append((a, b, text))
            continue
        start = round(a*RATE/fps)
        limit = round(cues[i+1][0]*RATE/fps)-round(BREATH*RATE) if i+1 < len(cues) else total
        room = max(round(b*RATE/fps), limit)-start
        if sound is None:
            sound = synthesize(phrase, speaker, rate)
        hurry = len(sound)/room*rate/max(rate, pace)
        if hurry > HURRY:
            rushed.append(f'{float(a/fps):8.2f}s  {hurry:.2f}x  {phrase}')
            continue
        if hurry > 1:
            faster.append((a, hurry))
        if len(sound) > room:
            # The voice reads faster more naturally than a recording compressed afterwards.
            if rate < 2 and len(sound) > room*1.05:
                sound = synthesize(phrase, speaker, min(2, rate*len(sound)/room))
            if len(sound) > room:
                sound = tempo(sound, len(sound)/room, room)
        fade = min(240, len(sound)//2)
        ramp = np.linspace(0, 1, fade, dtype=np.float32)
        sound[:fade] *= ramp
        sound[len(sound)-fade:] *= ramp[::-1]
        voice[start:start+len(sound)] = sound
        # Rounding to whole frames must not carry a cue into the next one or past the cut.
        end = cues[i+1][0] if i+1 < len(cues) else frames
        result.append((a, max(b, min(end, math.ceil((start+len(sound))*fps/RATE))), text))
    if rushed:
        raise ValueError(f'The voice would need more than {HURRY}x its pace for these cues '
                         '(delivered time); give each more time or split it:\n'+'\n'.join(rushed))
    if voice.any():
        voice = level(voice)
    pcm = np.rint(np.clip(voice, -1, 1)*32767).astype('<i2')
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-n', '-f', 's16le', '-ar', str(RATE),
                    '-ac', '1', '-i', '-', '-c:a', 'pcm_s16le', str(path)],
                   input=pcm.tobytes(), check=True)
    return result, faster
