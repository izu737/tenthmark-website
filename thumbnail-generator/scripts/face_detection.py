#!/usr/bin/env python3
"""
Face Direction Analysis Script
Analyzes face yaw/pitch angles in a thumbnail image using MediaPipe.
Usage: python3 face_detection.py <image_url_or_path> <output_folder>
Outputs JSON: {"yaw": float, "pitch": float, "roll": float, "face_detected": bool}
"""

import sys
import json
import os
import urllib.request
import tempfile

def download_image(url: str, dest_path: str) -> str:
    """Download image from URL or copy from local path."""
    if url.startswith(("http://", "https://")):
        headers = {"User-Agent": "Mozilla/5.0"}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            with open(dest_path, "wb") as f:
                f.write(resp.read())
        return dest_path
    return url


def analyze_face_angles(image_path: str) -> dict:
    """Analyze face yaw/pitch/roll using MediaPipe Face Mesh."""
    try:
        import mediapipe as mp
        import cv2
        import numpy as np

        mp_face_mesh = mp.solutions.face_mesh

        img = cv2.imread(image_path)
        if img is None:
            return {"yaw": 0.0, "pitch": 0.0, "roll": 0.0, "face_detected": False}

        h, w = img.shape[:2]
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        with mp_face_mesh.FaceMesh(
            static_image_mode=True,
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5
        ) as face_mesh:
            results = face_mesh.process(rgb)

        if not results.multi_face_landmarks:
            return {"yaw": 0.0, "pitch": 0.0, "roll": 0.0, "face_detected": False}

        lm = results.multi_face_landmarks[0].landmark

        # Key landmark indices for pose estimation
        # Nose tip: 1, Chin: 152, Left eye left corner: 263, Right eye right corner: 33
        # Left mouth: 287, Right mouth: 57
        landmark_indices = [1, 152, 263, 33, 287, 57]
        image_points = np.array([
            [lm[i].x * w, lm[i].y * h] for i in landmark_indices
        ], dtype=np.float64)

        # 3D model reference points (canonical face)
        model_points = np.array([
            [0.0, 0.0, 0.0],        # Nose tip
            [0.0, -63.6, -12.5],    # Chin
            [-43.3, 32.7, -26.0],   # Left eye left corner
            [43.3, 32.7, -26.0],    # Right eye right corner
            [-28.9, -28.9, -24.1],  # Left mouth corner
            [28.9, -28.9, -24.1]    # Right mouth corner
        ], dtype=np.float64)

        focal_length = w
        center = (w / 2, h / 2)
        camera_matrix = np.array([
            [focal_length, 0, center[0]],
            [0, focal_length, center[1]],
            [0, 0, 1]
        ], dtype=np.float64)

        dist_coeffs = np.zeros((4, 1))
        success, rotation_vector, _ = cv2.solvePnP(
            model_points, image_points, camera_matrix, dist_coeffs,
            flags=cv2.SOLVEPNP_ITERATIVE
        )

        if not success:
            return {"yaw": 0.0, "pitch": 0.0, "roll": 0.0, "face_detected": True}

        rmat, _ = cv2.Rodrigues(rotation_vector)
        # Decompose rotation matrix to Euler angles
        sy = np.sqrt(rmat[0, 0] ** 2 + rmat[1, 0] ** 2)
        singular = sy < 1e-6

        if not singular:
            pitch = np.degrees(np.arctan2(rmat[2, 1], rmat[2, 2]))
            yaw   = np.degrees(np.arctan2(-rmat[2, 0], sy))
            roll  = np.degrees(np.arctan2(rmat[1, 0], rmat[0, 0]))
        else:
            pitch = np.degrees(np.arctan2(-rmat[1, 2], rmat[1, 1]))
            yaw   = np.degrees(np.arctan2(-rmat[2, 0], sy))
            roll  = 0.0

        return {
            "yaw": round(float(yaw), 2),
            "pitch": round(float(pitch), 2),
            "roll": round(float(roll), 2),
            "face_detected": True
        }

    except ImportError as e:
        # Fallback: return neutral angles if MediaPipe not installed
        return {
            "yaw": 0.0,
            "pitch": 0.0,
            "roll": 0.0,
            "face_detected": False,
            "error": f"MediaPipe not available: {str(e)}"
        }
    except Exception as e:
        return {
            "yaw": 0.0,
            "pitch": 0.0,
            "roll": 0.0,
            "face_detected": False,
            "error": str(e)
        }


def main():
    if len(sys.argv) < 3:
        print(json.dumps({"error": "Usage: face_detection.py <image_url> <output_folder>"}))
        sys.exit(1)

    image_url = sys.argv[1]
    output_folder = sys.argv[2]
    os.makedirs(output_folder, exist_ok=True)

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        local_path = download_image(image_url, tmp_path)
        result = analyze_face_angles(local_path)
        print(json.dumps(result))
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


if __name__ == "__main__":
    main()
