#!/usr/bin/env python3
"""
render.py: turn an audio file into a Founders Podcast style text video.

Usage:
    python render.py episode1.mp3            # auto pick a font
    python render.py episode1.mp3 font.ttf   # use a specific font file

Optional flags:
    --model medium|medium.en|large|large-v2|large-v3   (default: medium)
    --retranscribe   ignore the cached transcript and run Whisper again

Output: output.mp4 (1920x1080, 30 fps, H.264 + AAC) written next to the audio file.
"""

import argparse
import bisect
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    sys.exit("Error: Pillow is not installed. Run: pip install Pillow")

try:
    from tqdm import tqdm
except ImportError:
    sys.exit("Error: tqdm is not installed. Run: pip install tqdm")


# ---------------------------------------------------------------------------
# Visual spec (all values come straight from the brief)
# ---------------------------------------------------------------------------
WIDTH, HEIGHT = 1920, 1080
FPS = 30
BACKGROUND = (255, 255, 255)        # #FFFFFF
INACTIVE_COLOR = (204, 204, 204)    # #CCCCCC, regular weight
ACTIVE_COLOR = (17, 17, 17)         # #111111, bold weight
FONT_SIZE = 72
LINE_HEIGHT = 1.4
LINES_PER_CHUNK = 3

LEFT_PADDING = 120                  # text block starts 120px from the left edge
RIGHT_PADDING = 120                 # lines never run closer than this to the right edge
MAX_LINE_WIDTH = WIDTH - LEFT_PADDING - RIGHT_PADDING
# Top of the 3 line block sits at the top of the middle third (y = 360).
# The block is about 302px tall, so it stays inside the middle third and its
# centre lands roughly 30px above the true centre of the frame.
TEXT_TOP = HEIGHT // 3

# Line breaking targets
MIN_WORDS, MAX_WORDS = 5, 7          # preferred words per line
HARD_MAX_WORDS = 10                  # never put more than this on a line
GAP_CLEARANCE = 0.6                  # min visible gap beside a bold word, in spaces

SUPPORTED_EXTENSIONS = {".mp3", ".wav"}
WHISPER_MODELS = ["medium", "medium.en", "large", "large-v2", "large-v3"]


def fail(message: str) -> None:
    """Print a clear error and stop."""
    sys.exit(f"Error: {message}")


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------
@dataclass
class Word:
    text: str
    start: float
    end: float


@dataclass
class Fonts:
    regular: ImageFont.FreeTypeFont
    bold: ImageFont.FreeTypeFont
    bold_stroke: int    # > 0 only when bold is faked with a stroke
    description: str


# ---------------------------------------------------------------------------
# Font discovery
# ---------------------------------------------------------------------------
# Preferred families in order, then common system fallbacks.
PREFERRED_FAMILIES = ["editorialnew", "canela", "sohne", "gtamerica", "georgia"]
FALLBACK_FAMILIES = ["dejavuserif", "liberationserif", "timesnewroman"]

REGULAR_STYLES = {"regular", "book", "roman", "normal"}
BOLD_STYLES = {"bold"}

FONT_DIRS = [
    Path.home() / ".fonts",
    Path.home() / ".local/share/fonts",
    Path("/usr/share/fonts"),
    Path("/usr/local/share/fonts"),
    Path.home() / "Library/Fonts",
    Path("/Library/Fonts"),
    Path("/System/Library/Fonts"),
    Path("/System/Library/Fonts/Supplemental"),
    Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Windows/Fonts",
]
FONT_EXTENSIONS = {".ttf", ".otf", ".ttc"}


def normalize_name(name: str) -> str:
    """Lowercase, strip accents (Söhne -> sohne) and drop non alphanumerics."""
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    return "".join(c for c in ascii_only.lower() if c.isalnum())


def font_identity(path: Path):
    """Return (family, style) normalized, or None if the file is not loadable."""
    try:
        family, style = ImageFont.truetype(str(path), 12).getname()
        return normalize_name(family or ""), normalize_name(style or "")
    except Exception:
        return None


def scan_fonts(directories):
    """Index every loadable font file as (family, style, path)."""
    found = []
    seen = set()
    for directory in directories:
        if not directory or not directory.is_dir():
            continue
        for path in directory.rglob("*"):
            if path.suffix.lower() not in FONT_EXTENSIONS or path in seen:
                continue
            seen.add(path)
            identity = font_identity(path)
            if identity:
                found.append((identity[0], identity[1], path))
    return found


def find_style(index, family_key: str, styles: set, exact_family: bool = False):
    """Find a non italic font file of the given family and style."""
    for family, style, path in index:
        family_match = family == family_key if exact_family else family_key in family
        if family_match and style in styles and "italic" not in style:
            return path
    return None


def try_variable_bold(path: Path):
    """If the font is a variable font with a Bold instance, return that instance."""
    try:
        font = ImageFont.truetype(str(path), FONT_SIZE)
        for name in font.get_variation_names():
            label = name.decode() if isinstance(name, bytes) else str(name)
            if normalize_name(label) == "bold":
                font.set_variation_by_name(name)
                return font
    except Exception:
        pass
    return None


def build_fonts(regular_path: Path, bold_path, origin: str) -> Fonts:
    """Load the regular and bold faces, faking bold with a stroke as a last resort."""
    regular = ImageFont.truetype(str(regular_path), FONT_SIZE)
    if bold_path:
        bold = ImageFont.truetype(str(bold_path), FONT_SIZE)
        return Fonts(regular, bold, 0, f"{origin}: {regular_path.name} + {bold_path.name}")

    variable_bold = try_variable_bold(regular_path)
    if variable_bold:
        return Fonts(regular, variable_bold, 0, f"{origin}: {regular_path.name} (variable Bold instance)")

    # No real bold available: draw the regular face with a thin outline in the same colour.
    stroke = max(1, round(FONT_SIZE * 0.025))
    print(f"Warning: no bold face found for {regular_path.name}; simulating bold with a {stroke}px stroke.")
    return Fonts(regular, regular, stroke, f"{origin}: {regular_path.name} (synthetic bold)")


def load_fonts(user_font) -> Fonts:
    """Resolve fonts: the user file first, then preferred families, then system fallbacks."""
    if user_font:
        path = Path(user_font).expanduser()
        if not path.is_file():
            fail(f"font file not found: {path}")
        identity = font_identity(path)
        if identity is None:
            fail(f"could not read font file (is it a valid .ttf/.otf?): {path}")
        family, style = identity
        if style in BOLD_STYLES:
            print("Warning: the font you passed is a Bold face; inactive words will also render bold.")
        # Look for the matching Bold file in the same folder (e.g. Font-Regular.otf + Font-Bold.otf).
        sibling_bold = find_style(scan_fonts([path.parent]), family, BOLD_STYLES, exact_family=True)
        if sibling_bold == path:
            sibling_bold = None
        return build_fonts(path, sibling_bold, "Font file")

    print("No font file given; searching installed fonts...")
    index = scan_fonts(FONT_DIRS)
    for family_key in PREFERRED_FAMILIES + FALLBACK_FAMILIES:
        regular = find_style(index, family_key, REGULAR_STYLES)
        if regular:
            bold = find_style(index, family_key, BOLD_STYLES)
            return build_fonts(regular, bold, "System font")

    fail(
        "no usable font found. Install Georgia (or Editorial New, Canela, Söhne, GT America) "
        "or pass a font file: python render.py audio.mp3 font.ttf"
    )


# ---------------------------------------------------------------------------
# Transcription (local open source Whisper, word level timestamps)
# ---------------------------------------------------------------------------
def transcript_cache_path(audio_path: Path) -> Path:
    return audio_path.with_name(audio_path.stem + ".words.json")


def audio_fingerprint(audio_path: Path) -> dict:
    stat = audio_path.stat()
    return {"size": stat.st_size, "mtime": int(stat.st_mtime)}


def load_cached_transcript(audio_path: Path, model_name: str):
    """Reuse a previous transcript if it came from the same audio file and model."""
    cache = transcript_cache_path(audio_path)
    if not cache.is_file():
        return None
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
        if data.get("model") != model_name or data.get("audio") != audio_fingerprint(audio_path):
            return None
        return [Word(w["text"], float(w["start"]), float(w["end"])) for w in data["words"]]
    except Exception:
        return None


def save_cached_transcript(audio_path: Path, model_name: str, words) -> None:
    cache = transcript_cache_path(audio_path)
    payload = {
        "model": model_name,
        "audio": audio_fingerprint(audio_path),
        "words": [{"text": w.text, "start": w.start, "end": w.end} for w in words],
    }
    try:
        cache.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as exc:
        print(f"Warning: could not save transcript cache ({exc}); continuing.")


def transcribe(audio_path: Path, model_name: str):
    """Run Whisper locally and return a flat list of Words with start/end times."""
    try:
        import torch
        import whisper
    except ImportError:
        fail("openai-whisper is not installed. Run: pip install openai-whisper")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Loading Whisper '{model_name}' on {device} (first run downloads the model)...")
    try:
        model = whisper.load_model(model_name, device=device)
    except Exception as exc:
        fail(f"could not load Whisper model '{model_name}': {exc}")

    print("Transcribing (this can take a while on CPU)...")
    try:
        result = model.transcribe(
            str(audio_path),
            word_timestamps=True,          # required for per word highlighting
            fp16=(device == "cuda"),       # fp16 is only supported on GPU
            verbose=False,                 # shows Whisper's own progress bar
        )
    except Exception as exc:
        fail(f"Whisper failed to transcribe the audio: {exc}")

    words = []
    for segment in result.get("segments", []):
        for item in segment.get("words", []):
            text = item.get("word", "").strip()
            if not text:
                continue
            # Punctuation only tokens (e.g. a stray dash) are glued onto the previous word.
            if words and not any(c.isalnum() for c in text):
                words[-1].text += text
                continue
            words.append(Word(text, float(item["start"]), float(item["end"])))
    return words


def clean_timestamps(words):
    """Force start times to be non decreasing and every end to be >= its start."""
    previous_start = 0.0
    for word in words:
        word.start = max(word.start, previous_start)
        word.end = max(word.end, word.start)
        previous_start = word.start
    return words


# ---------------------------------------------------------------------------
# Line breaking: 5 to 7 words per line, chosen at natural phrase breaks
# ---------------------------------------------------------------------------
# Words that make a good start for a new line (a new clause or phrase begins).
CLAUSE_STARTERS = {
    "and", "but", "or", "so", "because", "that", "which", "who", "whom", "whose",
    "when", "while", "if", "then", "where", "until", "although", "though", "since",
    "after", "before", "unless", "whether", "once", "yet", "nor",
}
PREPOSITIONS = {
    "to", "of", "in", "on", "for", "with", "at", "from", "by", "about", "into",
    "through", "over", "under", "like", "as", "between", "without", "against", "during",
}
# Words that read badly as the last word of a line (they lean on the next word).
WEAK_ENDINGS = {
    "the", "a", "an", "my", "your", "his", "her", "its", "our", "their", "this",
    "these", "those", "of", "to", "in", "on", "for", "with", "at", "from", "by",
    "and", "or", "but", "i", "i'm", "i've", "i'd", "you're", "we're", "they're",
    "it's", "is", "was", "be", "very", "so", "not", "no", "every", "some", "any",
}
TRAILING_QUOTES = "\"'”’)]"


def bare(word: str) -> str:
    """Lowercase word stripped of surrounding punctuation, for dictionary lookups."""
    return word.lower().strip(".,;:!?\"'“”‘’()[]\u2014\u2013-")


def word_count_cost(count: int, is_last_line: bool) -> float:
    """Penalty for a line holding `count` words; 5 to 7 is free."""
    if MIN_WORDS <= count <= MAX_WORDS:
        return 0.0
    if count < MIN_WORDS:
        if is_last_line:
            return 2.0 * (MIN_WORDS - count)   # a short final line is unavoidable
        return {4: 6.0, 3: 16.0, 2: 30.0, 1: 50.0}[count]
    return 8.0 * (count - MAX_WORDS) ** 1.5    # 8 words: 8, 9: 22.6, 10: 41.6


def break_cost(prev_word: str, next_word: str) -> float:
    """Cost of ending a line after prev_word (negative means a good place to break)."""
    tail = prev_word.rstrip(TRAILING_QUOTES)
    if tail.endswith((".", "?", "!")):
        return -12.0
    if tail.endswith((",", ";", ":", "\u2014", "\u2013", "...")):
        return -8.0
    cost = 0.0
    if bare(prev_word) in WEAK_ENDINGS:
        cost += 10.0
    next_bare = bare(next_word)
    if next_bare in CLAUSE_STARTERS:
        cost -= 4.0
    elif next_bare in PREPOSITIONS:
        cost -= 2.0
    return cost


def gap_for(extras, space_width: float) -> float:
    """
    Even word gap for a group of words. The active word is drawn bold and centred on
    its regular width, so it pushes half of its extra width into each neighbouring
    gap. The gap is widened just enough that a bold word never touches a neighbour.
    """
    largest = max(extras) if extras else 0.0
    return max(space_width, largest / 2 + space_width * GAP_CLEARANCE)


def break_into_lines(words, widths, extras, space_width):
    """
    Dynamic programming over every possible set of line breaks. Each line must fit
    MAX_LINE_WIDTH; the total cost (word count penalties + phrase break quality)
    is minimised, so breaks land on punctuation and clause boundaries.
    Returns a list of (start_index, end_index_exclusive).
    """
    n = len(words)
    prefix = [0.0]
    for width in widths:
        prefix.append(prefix[-1] + width)

    best = [math.inf] * (n + 1)
    choice = [0] * (n + 1)
    best[0] = 0.0
    for end in range(1, n + 1):
        largest_extra = 0.0
        for start in range(end - 1, max(0, end - HARD_MAX_WORDS) - 1, -1):
            largest_extra = max(largest_extra, extras[start])
            if best[start] == math.inf:
                continue
            count = end - start
            gap = gap_for([largest_extra], space_width)
            width = prefix[end] - prefix[start] + gap * (count - 1)
            if width > MAX_LINE_WIDTH and count > 1:
                continue
            is_last = end == n
            cost = best[start] + word_count_cost(count, is_last)
            if not is_last:
                cost += break_cost(words[end - 1].text, words[end].text)
            if cost < best[end]:
                best[end] = cost
                choice[end] = start

    lines = []
    end = n
    while end > 0:
        start = choice[end]
        lines.append((start, end))
        end = start
    return lines[::-1]


# ---------------------------------------------------------------------------
# Layout: fixed positions for every word so nothing shifts when a word turns bold
# ---------------------------------------------------------------------------
def layout(words, fonts: Fonts):
    """
    Returns (chunks, positions, word_to_chunk):
      chunks: list of lists of word indices (one list per 3 line screen)
      positions: (regular_x, bold_x, baseline_y) for every word
      word_to_chunk: chunk index for every word
    Words are spaced by their regular widths with one even gap per screen, and the
    bold version is centred on the regular one, so lines never reflow.
    """
    widths = [fonts.regular.getlength(w.text) for w in words]
    bold_widths = [fonts.bold.getlength(w.text) + 2 * fonts.bold_stroke for w in words]
    extras = [max(0.0, b - r) for b, r in zip(bold_widths, widths)]
    space_width = fonts.regular.getlength(" ")
    lines = break_into_lines(words, widths, extras, space_width)

    line_pitch = FONT_SIZE * LINE_HEIGHT
    half_leading = (line_pitch - FONT_SIZE) / 2
    ascent, _descent = fonts.regular.getmetrics()

    positions = [(0, 0, 0)] * len(words)
    chunks, word_to_chunk = [], [0] * len(words)
    for chunk_start in range(0, len(lines), LINES_PER_CHUNK):
        chunk_lines = lines[chunk_start:chunk_start + LINES_PER_CHUNK]
        chunk_index = len(chunks)
        chunk_words = []
        # One gap for the whole screen keeps spacing identical on all 3 lines.
        chunk_gap = gap_for([extras[i] for s, e in chunk_lines for i in range(s, e)], space_width)
        for row, (start, end) in enumerate(chunk_lines):
            gap = chunk_gap
            if sum(widths[start:end]) + gap * (end - start - 1) > MAX_LINE_WIDTH:
                # Rare: the shared gap would push this line past the margin; use its own gap.
                gap = gap_for(extras[start:end], space_width)
            baseline = TEXT_TOP + half_leading + ascent + row * line_pitch
            x = float(LEFT_PADDING)
            for i in range(start, end):
                # Bold glyphs (without any synthetic stroke) centred on the regular word.
                bold_x = x + (widths[i] - (bold_widths[i] - 2 * fonts.bold_stroke)) / 2
                positions[i] = (round(x), round(bold_x), round(baseline))
                word_to_chunk[i] = chunk_index
                chunk_words.append(i)
                x += widths[i] + gap
        chunks.append(chunk_words)
    return chunks, positions, word_to_chunk


# ---------------------------------------------------------------------------
# Frame rendering with Pillow
# ---------------------------------------------------------------------------
def render_frame(words, chunk_words, positions, active, fonts: Fonts) -> bytes:
    """Draw one 1920x1080 frame: every word grey/regular except the active one, black/bold."""
    image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image)
    for i in chunk_words:
        x, bold_x, y = positions[i]
        if i == active:
            stroke = fonts.bold_stroke
            draw.text((bold_x, y), words[i].text, font=fonts.bold, fill=ACTIVE_COLOR,
                      anchor="ls", stroke_width=stroke, stroke_fill=ACTIVE_COLOR)
        else:
            draw.text((x, y), words[i].text, font=fonts.regular, fill=INACTIVE_COLOR, anchor="ls")
    return image.tobytes()


def state_at(t, starts, words, word_to_chunk, chunk_count):
    """
    Which chunk is on screen and which word is active at time t.
    A word is active from its own start until the next word's start (the last word
    until its end). Before the first word the first chunk shows with nothing active;
    after the last word ends the last chunk stays with nothing active.
    """
    index = bisect.bisect_right(starts, t) - 1
    if index < 0:
        return 0, -1
    if index == len(words) - 1 and t >= words[-1].end:
        return chunk_count - 1, -1
    return word_to_chunk[index], index


# ---------------------------------------------------------------------------
# FFmpeg helpers
# ---------------------------------------------------------------------------
def check_ffmpeg() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            fail(f"{tool} was not found on PATH. Install FFmpeg (https://ffmpeg.org/download.html).")


def audio_duration(audio_path: Path) -> float:
    """Read the audio length in seconds with ffprobe."""
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        duration = float(result.stdout.strip())
    except ValueError:
        fail(f"ffprobe could not read the audio file: {result.stderr.strip() or 'unknown error'}")
    if duration <= 0:
        fail("the audio file has zero length.")
    return duration


def start_encoder(audio_path: Path, output_path: Path, log_file):
    """Start FFmpeg reading raw RGB frames on stdin and muxing in the original audio."""
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        # Video: raw frames from this script
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-video_size", f"{WIDTH}x{HEIGHT}",
        "-framerate", str(FPS), "-i", "-",
        # Audio: the original file
        "-i", str(audio_path),
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-tune", "stillimage",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest", "-movflags", "+faststart",
        str(output_path),
    ]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log_file)


def read_log(log_file) -> str:
    log_file.seek(0)
    return log_file.read().decode(errors="replace").strip()


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
def parse_args():
    parser = argparse.ArgumentParser(description="Render an audio file as a Founders style text video.")
    parser.add_argument("audio", help="path to an MP3 or WAV file")
    parser.add_argument("font", nargs="?", help="optional path to a .ttf/.otf font file")
    parser.add_argument("--model", default="medium", choices=WHISPER_MODELS,
                        help="Whisper model size (default: medium)")
    parser.add_argument("--retranscribe", action="store_true",
                        help="ignore the cached transcript and run Whisper again")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # 1. Validate inputs and tools
    audio_path = Path(args.audio).expanduser().resolve()
    if not audio_path.is_file():
        fail(f"audio file not found: {audio_path}")
    if audio_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        print(f"Warning: expected .mp3 or .wav, got '{audio_path.suffix}'. Trying anyway.")
    check_ffmpeg()
    duration = audio_duration(audio_path)
    output_path = audio_path.parent / "output.mp4"

    # 2. Fonts
    fonts = load_fonts(args.font)
    print(f"Using {fonts.description}")

    # 3. Word level transcript (cached next to the audio so re-renders are fast)
    words = None if args.retranscribe else load_cached_transcript(audio_path, args.model)
    if words:
        print(f"Using cached transcript: {transcript_cache_path(audio_path).name}")
    else:
        words = transcribe(audio_path, args.model)
        if words:
            save_cached_transcript(audio_path, args.model, words)
    if not words:
        fail("Whisper found no speech in the audio file.")
    words = clean_timestamps(words)
    print(f"{len(words)} words transcribed.")

    # 4. Layout: lines, 3 line chunks, fixed word positions
    chunks, positions, word_to_chunk = layout(words, fonts)
    print(f"{len(chunks)} screens of text.")

    # 5. Render every frame and stream it into FFmpeg
    total_frames = math.ceil(duration * FPS)
    starts = [w.start for w in words]
    print(f"Rendering {total_frames} frames ({duration:.1f}s at {FPS} fps) to {output_path}")

    with tempfile.TemporaryFile() as log_file:
        encoder = start_encoder(audio_path, output_path, log_file)
        last_state, frame = None, None
        try:
            for frame_index in tqdm(range(total_frames), unit="frame"):
                # Sample the middle of the frame's display interval, so a word lights up
                # on the frame closest to its timestamp (error under half a frame, ~17ms).
                t = (frame_index + 0.5) / FPS
                state = state_at(t, starts, words, word_to_chunk, len(chunks))
                # Most consecutive frames are identical; only redraw when the state changes.
                if state != last_state:
                    chunk_index, active = state
                    frame = render_frame(words, chunks[chunk_index], positions, active, fonts)
                    last_state = state
                encoder.stdin.write(frame)
            encoder.stdin.close()
            return_code = encoder.wait()
        except BrokenPipeError:
            encoder.wait()
            output_path.unlink(missing_ok=True)
            fail(f"FFmpeg stopped unexpectedly:\n{read_log(log_file)}")
        except KeyboardInterrupt:
            encoder.kill()
            encoder.wait()
            output_path.unlink(missing_ok=True)
            sys.exit("\nCancelled; partial output removed.")

        if return_code != 0:
            output_path.unlink(missing_ok=True)
            fail(f"FFmpeg failed (exit code {return_code}):\n{read_log(log_file)}")

    print(f"Done: {output_path}")


if __name__ == "__main__":
    main()
