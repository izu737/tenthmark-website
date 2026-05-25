"""
Thumbnail extraction and text overlay for viral clips.
Finds the sharpest/most-expressive frame from a clip, then composites
a title text overlay using Pillow.
"""

import cv2
import numpy as np
import json
import sys
import os
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


# ── Frame scoring ─────────────────────────────────────────────────────────────

def laplacian_variance(frame: np.ndarray) -> float:
    """Higher = sharper frame (less blurry)."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return cv2.Laplacian(gray, cv2.CV_64F).var()


def face_score(frame: np.ndarray) -> float:
    """Bonus score when a face is clearly visible and large."""
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = cascade.detectMultiScale(gray, 1.1, 5, minSize=(60, 60))
    if len(faces) == 0:
        return 0.0
    largest_area = max(f[2] * f[3] for f in faces)
    return min(largest_area / 10000.0, 50.0)  # cap bonus at 50


def brightness_score(frame: np.ndarray) -> float:
    """Penalise very dark or very bright (washed-out) frames."""
    mean = frame.mean()
    if mean < 30 or mean > 230:
        return -20.0
    return 0.0


def score_frame(frame: np.ndarray) -> float:
    return laplacian_variance(frame) + face_score(frame) + brightness_score(frame)


def extract_best_frame(
    video_path: str,
    start_sec: float,
    end_sec: float,
    sample_count: int = 20,
) -> tuple[np.ndarray, float]:
    """
    Sample `sample_count` frames between start_sec and end_sec.
    Return (best_frame, timestamp).
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    start_frame = int(start_sec * fps)
    end_frame = int(end_sec * fps)
    total = max(end_frame - start_frame, 1)
    step = max(total // sample_count, 1)

    best_frame = None
    best_score = -1.0
    best_time = start_sec

    for offset in range(0, total, step):
        idx = start_frame + offset
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = cap.read()
        if not ret:
            break
        s = score_frame(frame)
        if s > best_score:
            best_score = s
            best_frame = frame.copy()
            best_time = start_sec + offset / fps

    cap.release()
    return best_frame, best_time


# ── Text overlay ──────────────────────────────────────────────────────────────

DEFAULT_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FALLBACK_FONT_PATH = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"


def _load_font(size: int):
    if not PIL_AVAILABLE:
        return None
    for path in [DEFAULT_FONT_PATH, FALLBACK_FONT_PATH]:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _wrap_text(text: str, max_chars: int = 20) -> list[str]:
    words = text.split()
    lines, current = [], []
    for w in words:
        if sum(len(x) + 1 for x in current) + len(w) > max_chars and current:
            lines.append(" ".join(current))
            current = [w]
        else:
            current.append(w)
    if current:
        lines.append(" ".join(current))
    return lines


def add_text_overlay(
    frame_bgr: np.ndarray,
    title: str,
    score: float | None = None,
    viral_badge: bool = True,
) -> np.ndarray:
    """
    Composite text overlay onto a BGR frame (OpenCV format).
    Returns BGR frame with overlay applied.
    """
    if not PIL_AVAILABLE:
        # Fallback: use OpenCV putText
        h, w = frame_bgr.shape[:2]
        overlay = frame_bgr.copy()
        cv2.rectangle(overlay, (0, h - 120), (w, h), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.6, frame_bgr, 0.4, 0, frame_bgr)
        cv2.putText(frame_bgr, title[:40], (20, h - 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2)
        return frame_bgr

    h, w = frame_bgr.shape[:2]
    img = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(img)

    # Dark gradient bar at bottom
    bar_h = int(h * 0.3)
    gradient = Image.new("RGBA", (w, bar_h), (0, 0, 0, 0))
    for y in range(bar_h):
        alpha = int(200 * (y / bar_h))
        for x in range(w):
            gradient.putpixel((x, y), (0, 0, 0, alpha))
    img.paste(gradient, (0, h - bar_h), gradient)

    # Title text
    font_size = max(36, w // 18)
    font = _load_font(font_size)
    lines = _wrap_text(title.upper(), max_chars=18)
    line_h = font_size + 10
    y_start = h - bar_h + 20

    for i, line in enumerate(lines[:3]):
        # Shadow
        draw.text((22, y_start + i * line_h + 2), line, font=font, fill=(0, 0, 0, 180))
        draw.text((20, y_start + i * line_h), line, font=font, fill=(255, 255, 255, 255))

    # Viral score badge
    if viral_badge and score is not None:
        badge_text = f"VIRAL {int(score)}"
        badge_font = _load_font(max(24, w // 28))
        bx, by = w - 160, 20
        draw.rectangle([bx - 10, by - 5, bx + 150, by + 45], fill=(255, 60, 60, 220))
        draw.text((bx, by), badge_text, font=badge_font, fill=(255, 255, 255, 255))

    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


# ── Batch thumbnail generation ────────────────────────────────────────────────

def generate_thumbnails(
    video_path: str,
    segments: list[dict],
    output_dir: str,
) -> list[dict]:
    """
    Generate thumbnails for a list of clip segments.

    segments: list of {start, end, title, score}
    Returns: list of {segment_idx, thumbnail_path, frame_time}
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(video_path).stem
    results = []

    for i, seg in enumerate(segments):
        start = seg.get("start", 0)
        end = seg.get("end", start + 60)
        title = seg.get("title", seg.get("text", "")[:60])
        score = seg.get("score")

        print(f"Generating thumbnail {i + 1}/{len(segments)}: {start:.1f}s - {end:.1f}s")
        frame, frame_time = extract_best_frame(video_path, start, end)

        if frame is None:
            print(f"  Warning: no frame extracted for segment {i}")
            continue

        frame_with_text = add_text_overlay(frame, title, score=score)

        out_path = output_dir / f"{stem}_thumb_{i + 1:02d}.jpg"
        cv2.imwrite(str(out_path), frame_with_text, [cv2.IMWRITE_JPEG_QUALITY, 92])

        results.append({
            "segment_idx": i + 1,
            "thumbnail_path": str(out_path),
            "frame_time": round(frame_time, 2),
            "title": title,
            "score": score,
        })
        print(f"  Saved: {out_path}")

    return results


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python thumbnail_creation.py <video_path> <segments_json> [output_dir]")
        print("  segments_json: path to JSON array of {start, end, title, score} objects")
        sys.exit(1)

    vpath = sys.argv[1]
    segs_path = sys.argv[2]
    odir = sys.argv[3] if len(sys.argv) > 3 else "thumbnails"

    with open(segs_path) as f:
        segs = json.load(f)

    results = generate_thumbnails(vpath, segs, odir)
    print(json.dumps(results, indent=2))
