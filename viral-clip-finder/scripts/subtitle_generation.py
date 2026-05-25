"""
Subtitle generation from video audio using OpenAI Whisper.
Produces .srt files and animated ASS subtitle files with keyword highlighting.
"""

import os
import sys
import json
import re
import subprocess
import tempfile
from pathlib import Path
from dataclasses import dataclass


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class Segment:
    start: float
    end: float
    text: str


# ── Whisper transcription ─────────────────────────────────────────────────────

def extract_audio(video_path: str, out_path: str) -> None:
    """Extract mono 16kHz WAV audio from video for Whisper."""
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-ar", "16000", "-ac", "1", "-f", "wav", out_path
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def transcribe_whisper_api(audio_path: str, api_key: str, language: str = "en") -> list[Segment]:
    """Transcribe using the OpenAI Whisper API (whisper-1)."""
    import openai
    client = openai.OpenAI(api_key=api_key)

    with open(audio_path, "rb") as f:
        response = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            language=language,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )

    segments = []
    for seg in response.segments:
        segments.append(Segment(start=seg.start, end=seg.end, text=seg.text.strip()))
    return segments


def transcribe_whisper_local(audio_path: str, model_size: str = "base") -> list[Segment]:
    """Transcribe using local whisper package."""
    import whisper
    model = whisper.load_model(model_size)
    result = model.transcribe(audio_path, word_timestamps=False)
    segments = []
    for seg in result["segments"]:
        segments.append(Segment(start=seg["start"], end=seg["end"], text=seg["text"].strip()))
    return segments


# ── SRT generation ────────────────────────────────────────────────────────────

def _format_srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def segments_to_srt(segments: list[Segment], max_chars: int = 42) -> str:
    """Convert segments to SRT format, splitting long lines."""
    lines = []
    idx = 1
    for seg in segments:
        words = seg.text.split()
        chunks = []
        current = []
        for w in words:
            if sum(len(x) + 1 for x in current) + len(w) > max_chars and current:
                chunks.append(" ".join(current))
                current = [w]
            else:
                current.append(w)
        if current:
            chunks.append(" ".join(current))

        # Distribute time evenly across chunks
        duration = seg.end - seg.start
        chunk_dur = duration / max(len(chunks), 1)
        for i, chunk in enumerate(chunks):
            t_start = seg.start + i * chunk_dur
            t_end = t_start + chunk_dur
            lines.append(str(idx))
            lines.append(f"{_format_srt_time(t_start)} --> {_format_srt_time(t_end)}")
            lines.append(chunk)
            lines.append("")
            idx += 1

    return "\n".join(lines)


# ── Keyword highlighting ──────────────────────────────────────────────────────

HIGHLIGHT_KEYWORDS = [
    # High-signal viral words
    r"\b(secret|reveal|shocking|truth|exposed|never|always|only|must|every|zero|free)\b",
    r"\b(million|billion|viral|trending|hack|trick|mistake|wrong)\b",
    r"\b(how to|why|what if|imagine|stop|start|never do|always do)\b",
]

HIGHLIGHT_PATTERN = re.compile("|".join(HIGHLIGHT_KEYWORDS), re.IGNORECASE)


def highlight_keywords(text: str) -> str:
    """Wrap keywords in SRT bold/color markup for ffmpeg drawtext."""
    def replace(m):
        return f"<font color='#FFD700'><b>{m.group()}</b></font>"
    return HIGHLIGHT_PATTERN.sub(replace, text)


# ── ASS subtitle format (animated captions) ───────────────────────────────────

ASS_HEADER = """\
[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Montserrat,72,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,0,2,40,40,180,1
Style: Highlight,Montserrat,72,&H0000D7FF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,0,2,40,40,180,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _format_ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def segments_to_ass(segments: list[Segment], keywords: list[str] | None = None) -> str:
    """Generate ASS subtitle file with pop-on animation and optional keyword color."""
    extra_pattern = None
    if keywords:
        escaped = [re.escape(k) for k in keywords]
        extra_pattern = re.compile(r"\b(" + "|".join(escaped) + r")\b", re.IGNORECASE)

    events = [ASS_HEADER]
    for seg in segments:
        text = seg.text.strip()
        # Apply fade-in animation tag
        anim = r"{\fad(150,100)}"
        # Color specific keywords
        if extra_pattern:
            text = extra_pattern.sub(r"{\c&H00D7FF&}\1{\c&HFFFFFF&}", text)
        else:
            text = HIGHLIGHT_PATTERN.sub(r"{\c&H00D7FF&\b1}\g<0>{\b0\c&HFFFFFF&}", text)

        events.append(
            f"Dialogue: 0,{_format_ass_time(seg.start)},{_format_ass_time(seg.end)},"
            f"Default,,0,0,0,,{anim}{text}"
        )
    return "\n".join(events)


# ── Main entry point ──────────────────────────────────────────────────────────

def generate_subtitles(
    video_path: str,
    output_dir: str,
    api_key: str | None = None,
    language: str = "en",
    model_size: str = "base",
    keywords: list[str] | None = None,
) -> dict:
    """
    Full pipeline: extract audio → transcribe → write SRT + ASS files.

    Returns paths to generated files.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(video_path).stem

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        audio_path = tmp.name

    try:
        print(f"Extracting audio from {video_path}...")
        extract_audio(video_path, audio_path)

        print("Transcribing...")
        if api_key:
            segments = transcribe_whisper_api(audio_path, api_key, language)
        else:
            segments = transcribe_whisper_local(audio_path, model_size)

        srt_path = output_dir / f"{stem}.srt"
        ass_path = output_dir / f"{stem}.ass"
        json_path = output_dir / f"{stem}_transcript.json"

        srt_content = segments_to_srt(segments)
        ass_content = segments_to_ass(segments, keywords=keywords)
        transcript = [{"start": s.start, "end": s.end, "text": s.text} for s in segments]

        srt_path.write_text(srt_content, encoding="utf-8")
        ass_path.write_text(ass_content, encoding="utf-8")
        json_path.write_text(json.dumps(transcript, indent=2), encoding="utf-8")

        print(f"SRT  -> {srt_path}")
        print(f"ASS  -> {ass_path}")
        print(f"JSON -> {json_path}")

        return {
            "srt": str(srt_path),
            "ass": str(ass_path),
            "transcript_json": str(json_path),
            "segment_count": len(segments),
        }
    finally:
        os.unlink(audio_path)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python subtitle_generation.py <video_path> <output_dir> [whisper_api_key]")
        sys.exit(1)

    vpath = sys.argv[1]
    odir = sys.argv[2]
    key = sys.argv[3] if len(sys.argv) > 3 else None

    result = generate_subtitles(vpath, odir, api_key=key)
    print(json.dumps(result, indent=2))
