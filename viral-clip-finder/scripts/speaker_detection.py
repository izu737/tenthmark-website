"""
Speaker detection and optimal 9:16 crop box calculation.
Uses OpenCV face detection to track the speaker's position across frames
and compute the best crop window for vertical (9:16) format.
"""

import cv2
import numpy as np
import json
import sys
import os
from pathlib import Path


FACE_CASCADE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
PROFILE_CASCADE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_profileface.xml")


def detect_faces(frame: np.ndarray) -> list[tuple[int, int, int, int]]:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = FACE_CASCADE.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
    if len(faces) == 0:
        faces = PROFILE_CASCADE.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
    return [tuple(f) for f in faces] if len(faces) > 0 else []


def get_speaker_center(faces: list[tuple[int, int, int, int]], frame_w: int) -> int:
    """Return x-center of the largest face, defaulting to frame center."""
    if not faces:
        return frame_w // 2
    largest = max(faces, key=lambda f: f[2] * f[3])
    x, _, w, _ = largest
    return x + w // 2


def compute_crop_box(speaker_x: int, frame_w: int, frame_h: int) -> dict:
    """
    Compute the optimal 9:16 crop box (portrait) from a landscape frame.
    Returns x_offset, y_offset, crop_w, crop_h.
    """
    target_ratio = 9 / 16
    crop_h = frame_h
    crop_w = int(crop_h * target_ratio)

    if crop_w > frame_w:
        crop_w = frame_w
        crop_h = int(crop_w / target_ratio)

    half = crop_w // 2
    x_offset = max(0, min(speaker_x - half, frame_w - crop_w))
    y_offset = (frame_h - crop_h) // 2

    return {"x": x_offset, "y": y_offset, "w": crop_w, "h": crop_h}


def smooth_crop_positions(positions: list[dict], window: int = 30) -> list[dict]:
    """Apply moving average to reduce jitter in crop positions."""
    xs = [p["x"] for p in positions]
    smoothed = []
    for i, p in enumerate(positions):
        start = max(0, i - window // 2)
        end = min(len(xs), i + window // 2 + 1)
        avg_x = int(np.mean(xs[start:end]))
        smoothed.append({**p, "x": avg_x})
    return smoothed


def analyze_video(video_path: str, sample_fps: float = 2.0) -> dict:
    """
    Sample frames at sample_fps, detect speaker, and return crop metadata.

    Returns:
        {
            "frame_w": int,
            "frame_h": int,
            "duration": float,
            "fps": float,
            "crop_boxes": [{"time": float, "x": int, "y": int, "w": int, "h": int}, ...]
            "dominant_crop": {"x": int, "y": int, "w": int, "h": int}
        }
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps if fps > 0 else 0

    sample_interval = max(1, int(fps / sample_fps))
    crop_boxes = []
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx % sample_interval == 0:
            faces = detect_faces(frame)
            speaker_x = get_speaker_center(faces, frame_w)
            box = compute_crop_box(speaker_x, frame_w, frame_h)
            box["time"] = frame_idx / fps
            crop_boxes.append(box)
        frame_idx += 1

    cap.release()

    smoothed = smooth_crop_positions(crop_boxes)

    # Pick dominant x offset via histogram
    if smoothed:
        xs = [b["x"] for b in smoothed]
        dominant_x = int(np.median(xs))
        dominant_crop = {**smoothed[0], "x": dominant_x}
        del dominant_crop["time"]
    else:
        dominant_crop = compute_crop_box(frame_w // 2, frame_w, frame_h)

    return {
        "frame_w": frame_w,
        "frame_h": frame_h,
        "duration": round(duration, 2),
        "fps": round(fps, 2),
        "crop_boxes": smoothed,
        "dominant_crop": dominant_crop,
    }


def build_ffmpeg_crop_filter(crop: dict, use_dynamic: bool = False) -> str:
    """Return ffmpeg crop + scale filter string for 9:16 output at 1080x1920."""
    x, y, w, h = crop["x"], crop["y"], crop["w"], crop["h"]
    return f"crop={w}:{h}:{x}:{y},scale=1080:1920:flags=lanczos"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python speaker_detection.py <video_path> [output_json]")
        sys.exit(1)

    video_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None

    print(f"Analyzing: {video_path}")
    result = analyze_video(video_path)

    print(f"Resolution : {result['frame_w']}x{result['frame_h']}")
    print(f"Duration   : {result['duration']}s")
    print(f"Dominant crop: {result['dominant_crop']}")
    print(f"FFmpeg filter: {build_ffmpeg_crop_filter(result['dominant_crop'])}")

    if output_path:
        with open(output_path, "w") as f:
            json.dump(result, f, indent=2)
        print(f"Saved to: {output_path}")
    else:
        print(json.dumps(result, indent=2))
