"""
pauses.py: shorten long pauses without touching speech or flattening the speaker's cadence.

How it decides, in plain terms:
  * Silence is measured from the audio itself, in 10 ms steps. Whisper's word timings are
    only used for context (which words sit either side of a pause, and whether the pause
    follows the end of a sentence). Whisper is often a tenth of a second or more off, so it
    is never trusted to say where speech starts or stops.
  * Short pauses are left exactly as they are. Long pauses are shortened in proportion, so a
    long pause still ends up longer than a medium one and the rhythm of the delivery survives.
  * Only the middle of a confirmed silence is removed. A margin of silence is kept after the
    last sound and before the next one, so word endings, breaths and room tone stay intact.
  * Anything with sound in it (a breath, a laugh, music, a word Whisper missed) is never cut.
  * Every join gets a short equal power crossfade inside the silence, so there are no clicks.
  * After editing, the result is measured again. If any sound from the original is missing,
    the edit is rejected and the original audio is used.

Every rule is a named constant below, so it can be tuned after listening.
"""

import csv
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------- the rules
KEEP_MID = 0.60          # pauses up to this long (s) inside a sentence are untouched
KEEP_SENTENCE = 0.80     # ... and after a full stop, question mark or exclamation mark
KEEP_SHARE = 0.30        # a longer pause keeps this share of the time above the threshold
CAP_MID = 1.00           # never shorten a mid sentence pause below its untouched part, never leave it above this
CAP_SENTENCE = 1.30      # same, after the end of a sentence
LEAD_KEEP = 0.30         # silence kept at the very start of the file
TAIL_KEEP = 0.80         # silence kept at the very end
MARGIN_AFTER = 0.12      # silence always kept after the last sound before a pause
MARGIN_BEFORE = 0.10     # silence always kept before the first sound after a pause
MIN_SILENCE = 0.25       # shorter silences are treated as part of speech (stops, consonants)
MIN_CUT = 0.05           # do not bother with cuts shorter than this
MIN_SNR_DB = 20          # speech must be this much louder than the room noise, or nothing is cut
WORD_GUARD = 0.05        # cuts stay this far from any word Whisper heard
CROSSFADE = 0.020        # seconds of equal power crossfade at every join

HOP = 0.010              # analysis step (s)
WINDOW = 0.030           # analysis window (s)


@dataclass
class Pause:
    start: float          # where the measured silence starts (s, original timeline)
    end: float            # where it ends
    kind: str             # "leading", "mid", "sentence" or "trailing"
    before: str           # word before the pause
    after: str            # word after the pause
    new_length: float     # silence length after editing
    cut_start: float = 0.0
    cut_end: float = 0.0

    @property
    def length(self):
        return self.end - self.start

    @property
    def removed(self):
        return self.cut_end - self.cut_start


# ---------------------------------------------------------------- audio in and out
def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                          "stream=sample_rate,channels", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True).stdout.strip().split(",")
    return int(out[0]), int(out[1])


def load_audio(path):
    """Decode any audio file to float32 samples, shape (n, channels), at its own sample rate."""
    sr, ch = probe(path)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-acodec", "pcm_f32le",
                          "-ac", str(ch), "-ar", str(sr), "-"], capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32).reshape(-1, ch).copy(), sr


def save_wav(path, samples, sr):
    ch = samples.shape[1]
    p = subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(sr), "-ac", str(ch), "-i", "-",
                        "-c:a", "pcm_s24le", str(path)], input=samples.astype(np.float32).tobytes())
    if p.returncode != 0:
        raise RuntimeError("could not write the tightened audio")


# ---------------------------------------------------------------- measuring silence
def loudness_db(samples, sr):
    """Loudness in dB for every 10 ms step (30 ms window)."""
    mono = samples.mean(axis=1)
    hop, win = int(sr * HOP), int(sr * WINDOW)
    n = max(1, (len(mono) - win) // hop + 1)
    idx = np.arange(win)[None, :] + hop * np.arange(n)[:, None]
    frames = mono[np.clip(idx, 0, len(mono) - 1)]
    rms = np.sqrt((frames ** 2).mean(axis=1))
    return 20 * np.log10(rms + 1e-9)


def silence_threshold(db, words):
    """A level clearly above the room noise and clearly below speech."""
    floor = np.percentile(db, 5)
    speech = []
    for w in words:
        a, b = int(w.start / HOP), int(w.end / HOP)
        speech.extend(db[a:b].tolist())
    speech_level = np.median(speech) if speech else np.percentile(db, 90)
    # 35% of the way from room noise up to speech, but never closer than 6 dB to the noise
    # (that rule wins, so a noisy recording makes detection more careful, never more aggressive)
    thr = floor + 0.35 * (speech_level - floor)
    thr = min(thr, speech_level - 20)
    thr = max(thr, floor + 6)
    return float(thr), float(floor), float(speech_level)


def silent_runs(db, thr):
    """(start, end) in seconds of every stretch quieter than thr for at least MIN_SILENCE."""
    quiet = db < thr
    runs, i, n = [], 0, len(quiet)
    while i < n:
        if quiet[i]:
            j = i
            while j < n and quiet[j]:
                j += 1
            # a frame covers [i*HOP, i*HOP + WINDOW]; trim so the run is quiet throughout
            s, e = i * HOP + WINDOW / 2, j * HOP + WINDOW / 2
            if e - s >= MIN_SILENCE:
                runs.append((s, e))
            i = j
        else:
            i += 1
    return runs


# ---------------------------------------------------------------- the plan
def target_length(length, kind):
    if kind == "leading":
        return min(length, LEAD_KEEP)
    if kind == "trailing":
        return min(length, TAIL_KEEP)
    keep, cap = (KEEP_SENTENCE, CAP_SENTENCE) if kind == "sentence" else (KEEP_MID, CAP_MID)
    if length <= keep:
        return length
    return min(keep + KEEP_SHARE * (length - keep), max(cap, keep))


def plan(audio_path, words):
    """Measure every pause and decide how much (if anything) to take out of it."""
    samples, sr = load_audio(audio_path)
    duration = len(samples) / sr
    db = loudness_db(samples, sr)
    thr, floor, speech = silence_threshold(db, words)
    info = {"threshold_db": thr, "noise_floor_db": floor, "speech_db": speech, "duration": duration,
            "refused": None}
    if speech - floor < MIN_SNR_DB:
        info["refused"] = (f"the recording is too noisy to tell quiet speech from silence safely "
                           f"(speech is only {speech - floor:.0f} dB above the room noise; "
                           f"at least {MIN_SNR_DB} dB is needed)")
        return [], info
    pauses = []
    for s, e in silent_runs(db, thr):
        # a word Whisper heard entirely inside this "silence" was spoken very quietly: keep it all
        if any(w.start > s + 0.05 and w.end < e - 0.05 for w in words):
            continue
        before = [w for w in words if w.start < s]
        after = [w for w in words if w.start >= s]
        if not before:
            kind = "leading"
        elif not after or s >= words[-1].end - 0.05 and e >= duration - 0.02:
            kind = "trailing"
        else:
            kind = "sentence" if before[-1].text.rstrip('"\')]”’').endswith((".", "?", "!")) else "mid"
        p = Pause(s, min(e, duration), kind, before[-1].text if before else "", after[0].text if after else "", 0.0)
        p.new_length = target_length(p.length, kind)
        remove = p.length - p.new_length
        lo = p.start + (0 if kind == "leading" else MARGIN_AFTER)
        hi = p.end - (0 if kind == "trailing" else MARGIN_BEFORE)
        # never cut where Whisper heard a word: take the longest stretch free of words
        free = [(lo, hi)]
        for w in words:
            a, b = w.start - WORD_GUARD, w.end + WORD_GUARD
            nxt = []
            for x, y in free:
                if b <= x or a >= y:
                    nxt.append((x, y))
                else:
                    if a > x: nxt.append((x, a))
                    if b < y: nxt.append((b, y))
            free = nxt
        lo, hi = max(free, key=lambda r: r[1] - r[0]) if free else (lo, lo)
        remove = min(remove, max(0.0, hi - lo))
        if remove >= MIN_CUT:
            if kind == "leading":
                p.cut_start, p.cut_end = lo, lo + remove        # remove the earliest silence, keep what leads into speech
            elif kind == "trailing":
                p.cut_start, p.cut_end = hi - remove, hi        # remove the last silence, keep what follows speech
            else:
                mid = (lo + hi) / 2
                p.cut_start, p.cut_end = mid - remove / 2, mid + remove / 2
            p.new_length = p.length - remove
        else:
            p.new_length = p.length
            p.cut_start = p.cut_end = p.start
        pauses.append(p)
    return pauses, info


# ---------------------------------------------------------------- applying it
def apply(audio_path, pauses, out_path):
    """Remove the planned spans with crossfades. Returns the new duration."""
    samples, sr = load_audio(audio_path)
    xf = max(2, int(sr * CROSSFADE))
    cuts = sorted([(int(round(p.cut_start * sr)), int(round(p.cut_end * sr))) for p in pauses if p.removed > 0])
    pieces, pos = [], 0
    for a, b in cuts:
        # keep half a crossfade either side of the cut; the overlap then removes exactly b - a
        pieces.append(samples[pos:a + xf // 2])
        pos = b - xf // 2
    pieces.append(samples[pos:])
    out = pieces[0]
    for piece in pieces[1:]:
        n = min(xf, len(out), len(piece))          # cuts at the very start or end can be shorter
        if n == 0:
            out = np.concatenate([out, piece])
            continue
        fo = np.cos(np.linspace(0, np.pi / 2, n, dtype=np.float32))[:, None]
        fi = np.sin(np.linspace(0, np.pi / 2, n, dtype=np.float32))[:, None]
        blended = out[len(out) - n:] * fo + piece[:n] * fi
        out = np.concatenate([out[:len(out) - n], blended, piece[n:]])
    save_wav(out_path, out, sr)
    return len(out) / sr


def remap(t, pauses):
    """Original time -> edited time."""
    shift = 0.0
    for p in pauses:
        if p.removed <= 0:
            continue
        if t >= p.cut_end:
            shift += p.removed
        elif t > p.cut_start:
            shift += t - p.cut_start
    return t - shift


def verify(original_path, edited_path, pauses, threshold_db):
    """Check that every sound in the original is still in the edit.

    Counts the 10 ms steps that are louder than the silence threshold in both files. Cuts are
    only made inside silence, so these counts must match (allowing one step per join for the
    crossfade). Returns (ok, message)."""
    a, sr = load_audio(original_path)
    b, sr2 = load_audio(edited_path)
    loud_a = int((loudness_db(a, sr) >= threshold_db).sum())
    loud_b = int((loudness_db(b, sr2) >= threshold_db).sum())
    joins = sum(1 for p in pauses if p.removed > 0)
    removed = sum(p.removed for p in pauses)
    expected = len(a) / sr - removed
    length_ok = abs(len(b) / sr2 - expected) < 0.01
    sound_ok = abs(loud_a - loud_b) <= joins + 2
    msg = (f"sound kept: {loud_b} of {loud_a} loud 10 ms steps; "
           f"length {len(b) / sr2:.2f}s (expected {expected:.2f}s)")
    return length_ok and sound_ok, msg


# ---------------------------------------------------------------- report
def fmt(t):
    return f"{int(t // 60)}:{t % 60:05.2f}"


def write_report(pauses, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["at", "after word", "before word", "type", "pause (s)", "becomes (s)", "removed (s)"])
        for p in pauses:
            w.writerow([fmt(p.start), p.before, p.after, p.kind, f"{p.length:.2f}", f"{p.new_length:.2f}", f"{p.removed:.2f}"])


def summary(pauses, info):
    if info.get("refused"):
        return f"Pauses not changed: {info['refused']}."
    changed = [p for p in pauses if p.removed > 0]
    removed = sum(p.removed for p in changed)
    lines = [
        f"Pauses measured: {len(pauses)} (silence threshold {info['threshold_db']:.0f} dB, "
        f"room noise {info['noise_floor_db']:.0f} dB, speech {info['speech_db']:.0f} dB)",
        f"Pauses shortened: {len(changed)}; left exactly as they were: {len(pauses) - len(changed)}",
        f"Time removed: {removed:.1f}s of {info['duration']:.1f}s ({100 * removed / max(info['duration'], 1e-9):.1f}%)",
    ]
    if changed:
        longest = max(changed, key=lambda p: p.length)
        lines.append(f"Longest pause: {longest.length:.2f}s after \"{longest.before}\" at {fmt(longest.start)}, "
                     f"now {longest.new_length:.2f}s")
    return "\n".join(lines)
