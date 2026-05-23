#!/usr/bin/env python3
"""
silence_detection.py
Detects speech and silence segments in an audio file using Silero VAD.

Usage:
    python3 silence_detection.py <audio_wav_path> <output_json_path> [silence_threshold_seconds]

Output JSON:
    {
        "speech_segments": [{"start": 0.0, "end": 1.5}, ...],
        "silence_segments": [{"start": 1.5, "end": 2.1}, ...],
        "duration": 120.3
    }
"""

import sys
import json
import os
import traceback


def detect_speech_segments(audio_path, silence_threshold=0.5):
    import torch
    import torchaudio

    # Load Silero VAD model from torch hub
    model, utils = torch.hub.load(
        repo_or_dir="snakers4/silero-vad",
        model="silero_vad",
        force_reload=False,
        trust_repo=True,
    )
    (get_speech_timestamps, _, read_audio, _, _) = utils

    # Read audio (must be 16kHz mono WAV)
    wav = read_audio(audio_path, sampling_rate=16000)
    sample_rate = 16000
    duration = len(wav) / sample_rate

    print(f"Audio duration: {duration:.2f}s", file=sys.stderr)

    # Run VAD
    speech_timestamps = get_speech_timestamps(
        wav,
        model,
        sampling_rate=sample_rate,
        threshold=0.5,
        min_speech_duration_ms=250,
        min_silence_duration_ms=int(silence_threshold * 1000),
    )

    # Convert sample indices to seconds
    speech_segments = []
    for seg in speech_timestamps:
        speech_segments.append({
            "start": round(seg["start"] / sample_rate, 3),
            "end": round(seg["end"] / sample_rate, 3),
        })

    # Derive silence segments as gaps between speech
    silence_segments = []
    prev_end = 0.0
    for seg in speech_segments:
        gap = seg["start"] - prev_end
        if gap >= silence_threshold:
            silence_segments.append({"start": round(prev_end, 3), "end": round(seg["start"], 3)})
        prev_end = seg["end"]
    if duration - prev_end >= silence_threshold:
        silence_segments.append({"start": round(prev_end, 3), "end": round(duration, 3)})

    return {
        "speech_segments": speech_segments,
        "silence_segments": silence_segments,
        "duration": round(duration, 3),
    }


def main():
    if len(sys.argv) < 3:
        print(
            json.dumps({"error": "Usage: silence_detection.py <audio_path> <output_json> [threshold]"}),
            file=sys.stderr,
        )
        sys.exit(1)

    audio_path = sys.argv[1]
    output_json_path = sys.argv[2]
    silence_threshold = float(sys.argv[3]) if len(sys.argv) > 3 else 0.5

    if not os.path.isfile(audio_path):
        result = {"error": f"Audio file not found: {audio_path}"}
        print(json.dumps(result))
        sys.exit(1)

    try:
        print(f"Running silence detection on: {audio_path}", file=sys.stderr)
        print(f"Silence threshold: {silence_threshold}s", file=sys.stderr)

        result = detect_speech_segments(audio_path, silence_threshold)

        print(f"Detected {len(result['speech_segments'])} speech segments", file=sys.stderr)
        print(f"Detected {len(result['silence_segments'])} silence gaps", file=sys.stderr)

        with open(output_json_path, "w") as f:
            json.dump(result, f, indent=2)

        # Print to stdout so n8n Execute Command node captures it
        print(json.dumps(result))

    except Exception as e:
        error_result = {"error": str(e), "traceback": traceback.format_exc()}
        print(json.dumps(error_result))
        sys.exit(1)


if __name__ == "__main__":
    main()
