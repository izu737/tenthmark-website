"""
Clip generation pipeline: crop, subtitle burn, hook overlay, CTA, audio normalisation.
Wraps FFmpeg subprocess calls with structured argument building.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def run_ffmpeg(args: list[str], description: str = "") -> None:
    cmd = ["ffmpeg", "-y", "-loglevel", "error"] + args
    print(f"  FFmpeg: {description or ' '.join(args[:6])}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg failed:\n{result.stderr}")


def extract_clip(
    src: str,
    out: str,
    start: float,
    end: float,
) -> None:
    duration = end - start
    run_ffmpeg(
        ["-ss", str(start), "-i", src, "-t", str(duration),
         "-c", "copy", "-avoid_negative_ts", "make_zero", out],
        f"extract {start:.1f}s-{end:.1f}s",
    )


def crop_to_vertical(
    src: str,
    out: str,
    crop_x: int,
    crop_y: int,
    crop_w: int,
    crop_h: int,
) -> None:
    vf = f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y},scale=1080:1920:flags=lanczos"
    run_ffmpeg(
        ["-i", src, "-vf", vf, "-c:v", "libx264", "-preset", "fast",
         "-crf", "22", "-c:a", "copy", out],
        "crop to 9:16",
    )


def burn_subtitles(src: str, ass_path: str, out: str) -> None:
    vf = f"ass={ass_path}"
    run_ffmpeg(
        ["-i", src, "-vf", vf, "-c:v", "libx264", "-preset", "fast",
         "-crf", "22", "-c:a", "copy", out],
        "burn subtitles",
    )


def add_hook_overlay(
    src: str,
    out: str,
    hook_text: str,
    duration: float = 3.0,
    font_path: str = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
) -> None:
    safe_text = hook_text.replace("'", "\\'").replace(":", "\\:")
    # Word-wrap at ~25 chars
    words = safe_text.split()
    lines, cur = [], []
    for w in words:
        if sum(len(x) + 1 for x in cur) + len(w) > 25 and cur:
            lines.append(" ".join(cur))
            cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(" ".join(cur))

    drawtext_filters = []
    for i, line in enumerate(lines[:3]):
        y = f"(h*0.08)+{i * 80}"
        drawtext_filters.append(
            f"drawtext=fontfile={font_path}:text='{line}':"
            f"fontsize=64:fontcolor=white:borderw=4:bordercolor=black:"
            f"x=(w-text_w)/2:y={y}:"
            f"enable='between(t,0,{duration})'"
        )

    vf = ",".join(drawtext_filters)
    run_ffmpeg(
        ["-i", src, "-vf", vf, "-c:v", "libx264", "-preset", "fast",
         "-crf", "22", "-c:a", "copy", out],
        "add hook text",
    )


def add_cta_endscreen(
    src: str,
    out: str,
    channel_name: str = "Watch Full Video",
    cta_text: str = "Watch full video →",
    cta_duration: float = 3.0,
    font_path: str = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
) -> None:
    """Add a CTA overlay in the last `cta_duration` seconds."""
    # Get video duration
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", src],
        capture_output=True, text=True
    )
    total = float(probe.stdout.strip() or 0)
    cta_start = max(0, total - cta_duration)

    safe_cta = cta_text.replace("'", "\\'").replace(":", "\\:")
    safe_ch = channel_name.replace("'", "\\'").replace(":", "\\:")

    vf = (
        f"drawtext=fontfile={font_path}:text='{safe_cta}':"
        f"fontsize=56:fontcolor=white:borderw=4:bordercolor=black:"
        f"x=(w-text_w)/2:y=(h*0.78):"
        f"enable='between(t,{cta_start},{total})',"
        f"drawtext=fontfile={font_path}:text='{safe_ch}':"
        f"fontsize=40:fontcolor=#FFD700:borderw=3:bordercolor=black:"
        f"x=(w-text_w)/2:y=(h*0.84):"
        f"enable='between(t,{cta_start},{total})'"
    )
    run_ffmpeg(
        ["-i", src, "-vf", vf, "-c:v", "libx264", "-preset", "fast",
         "-crf", "22", "-c:a", "copy", out],
        "add CTA end screen",
    )


def normalise_audio(src: str, out: str, target_lufs: float = -14.0) -> None:
    """Two-pass loudnorm for broadcast-level audio normalisation."""
    # Pass 1: measure
    probe_cmd = [
        "ffmpeg", "-i", src,
        "-af", f"loudnorm=I={target_lufs}:TP=-2:LRA=11:print_format=json",
        "-f", "null", "-"
    ]
    result = subprocess.run(probe_cmd, capture_output=True, text=True)
    stderr = result.stderr

    # Extract loudnorm JSON from stderr
    try:
        start = stderr.rfind("{")
        end = stderr.rfind("}") + 1
        ln_data = json.loads(stderr[start:end])
        measured_i = ln_data["input_i"]
        measured_tp = ln_data["input_tp"]
        measured_lra = ln_data["input_lra"]
        measured_thresh = ln_data["input_thresh"]
        offset = ln_data["target_offset"]
    except (json.JSONDecodeError, KeyError):
        measured_i = measured_tp = measured_lra = measured_thresh = offset = "-inf"

    # Pass 2: apply
    af = (
        f"loudnorm=I={target_lufs}:TP=-2:LRA=11:"
        f"measured_I={measured_i}:measured_TP={measured_tp}:"
        f"measured_LRA={measured_lra}:measured_thresh={measured_thresh}:"
        f"offset={offset}:linear=true:print_format=none"
    )
    run_ffmpeg(
        ["-i", src, "-af", af, "-c:v", "copy", out],
        f"normalise audio to {target_lufs} LUFS",
    )


def add_music_bed(
    src: str,
    music_path: str,
    out: str,
    music_volume: float = 0.08,
) -> None:
    """Mix a background music track under the original audio."""
    run_ffmpeg(
        ["-i", src, "-stream_loop", "-1", "-i", music_path,
         "-filter_complex",
         f"[1:a]volume={music_volume}[bg];[0:a][bg]amix=inputs=2:duration=first[aout]",
         "-map", "0:v", "-map", "[aout]",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", out],
        "add music bed",
    )


def process_clip(
    src_video: str,
    segment: dict,
    crop_data: dict,
    ass_file: str | None,
    output_path: str,
    channel_name: str = "Watch Full Video",
    music_path: str | None = None,
) -> str:
    """
    Full clip processing pipeline for one segment.
    Returns path to final output file.
    """
    start = segment["start"]
    end = segment["end"]
    hook_text = segment.get("hook_text", "")

    tmp_dir = tempfile.mkdtemp()
    steps = {
        "raw": os.path.join(tmp_dir, "01_raw.mp4"),
        "cropped": os.path.join(tmp_dir, "02_cropped.mp4"),
        "subtitled": os.path.join(tmp_dir, "03_subtitled.mp4"),
        "hooked": os.path.join(tmp_dir, "04_hooked.mp4"),
        "cta": os.path.join(tmp_dir, "05_cta.mp4"),
        "audio": os.path.join(tmp_dir, "06_audio.mp4"),
    }

    print(f"\nProcessing clip: {start:.1f}s - {end:.1f}s")

    extract_clip(src_video, steps["raw"], start, end)

    crop_to_vertical(
        steps["raw"], steps["cropped"],
        crop_data["x"], crop_data["y"],
        crop_data["w"], crop_data["h"],
    )

    if ass_file and os.path.exists(ass_file):
        burn_subtitles(steps["cropped"], ass_file, steps["subtitled"])
    else:
        steps["subtitled"] = steps["cropped"]

    if hook_text:
        add_hook_overlay(steps["subtitled"], steps["hooked"], hook_text)
    else:
        steps["hooked"] = steps["subtitled"]

    add_cta_endscreen(steps["hooked"], steps["cta"], channel_name=channel_name)

    if music_path and os.path.exists(music_path):
        normalise_audio(steps["cta"], steps["audio"])
        add_music_bed(steps["audio"], music_path, output_path)
    else:
        normalise_audio(steps["cta"], output_path)

    # Cleanup temp files
    for p in steps.values():
        if os.path.exists(p) and p != output_path:
            os.unlink(p)
    os.rmdir(tmp_dir)

    print(f"  Final clip saved: {output_path}")
    return output_path


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python clip_generator.py <video> <scored_segments.json> <output_dir> [channel_name] [music.mp3]")
        sys.exit(1)

    vpath = sys.argv[1]
    segs_path = sys.argv[2]
    odir = Path(sys.argv[3])
    channel = sys.argv[4] if len(sys.argv) > 4 else "Watch Full Video"
    music = sys.argv[5] if len(sys.argv) > 5 else None

    odir.mkdir(parents=True, exist_ok=True)

    with open(segs_path) as f:
        segments = json.load(f)

    # Dummy crop for CLI standalone use — replace with speaker_detection output
    crop = {"x": 0, "y": 0, "w": 608, "h": 1080}

    results = []
    for i, seg in enumerate(segments[:7]):
        out_path = str(odir / f"clip_{i + 1:02d}_{seg.get('composite_score', 0):.0f}.mp4")
        path = process_clip(vpath, seg, crop, None, out_path, channel_name=channel, music_path=music)
        results.append({"clip": path, "score": seg.get("composite_score"), "title": seg.get("suggested_title")})

    print(json.dumps(results, indent=2))
