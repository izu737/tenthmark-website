#!/usr/bin/env python3
"""
trigger_word_detection.py
Detects spoken trigger words ("cut this", "remove this") in a video/audio file
using OpenAI Whisper. Returns timestamps of segments to delete.

Usage:
    python3 trigger_word_detection.py <video_or_audio_path> <output_json_path> [whisper_model]

    whisper_model: tiny | base | small | medium | large  (default: base)

Output JSON:
    {
        "cut_segments": [{"start": 12.4, "end": 15.1}, ...],
        "full_transcript": "...",
        "duration": 120.3
    }
"""

import sys
import json
import os
import traceback

TRIGGER_PHRASES = ["cut this", "remove this"]


def find_sentence_start(segments, trigger_segment_index):
    """
    Walk back from the trigger segment to find where the preceding sentence began.
    We look for the previous segment whose text ends with sentence-ending punctuation,
    or fall back to the start of the segment directly before the trigger.
    """
    if trigger_segment_index == 0:
        return 0.0

    sentence_endings = {".", "!", "?", "...", '."', '!"', '?"'}

    for i in range(trigger_segment_index - 1, -1, -1):
        text = segments[i]["text"].strip()
        for ending in sentence_endings:
            if text.endswith(ending):
                # Sentence ended here; the mistake starts at the NEXT segment
                if i + 1 < trigger_segment_index:
                    return segments[i + 1]["start"]
                return segments[i]["end"]

    # No sentence boundary found — go back to start of previous segment
    return segments[trigger_segment_index - 1]["start"]


def detect_trigger_words(video_path, model_name="base"):
    import whisper

    print(f"Loading Whisper model '{model_name}'...", file=sys.stderr)
    model = whisper.load_model(model_name)

    print(f"Transcribing: {video_path}", file=sys.stderr)
    result = model.transcribe(video_path, verbose=False)

    segments = result.get("segments", [])
    duration = segments[-1]["end"] if segments else 0.0
    full_transcript = result.get("text", "").strip()

    print(f"Transcribed {len(segments)} segments, duration {duration:.2f}s", file=sys.stderr)

    cut_segments = []
    skip_until = -1  # Avoid double-counting overlapping triggers

    for i, segment in enumerate(segments):
        if segment["start"] < skip_until:
            continue

        text_lower = segment["text"].lower().strip()

        triggered = any(phrase in text_lower for phrase in TRIGGER_PHRASES)
        if not triggered:
            continue

        # Rewind to the start of the mistake sentence
        mistake_start = find_sentence_start(segments, i)
        mistake_end = segment["end"]

        print(
            f"Trigger found at segment {i}: '{segment['text'].strip()}' "
            f"| cutting [{mistake_start:.2f}s – {mistake_end:.2f}s]",
            file=sys.stderr,
        )

        cut_segments.append({
            "start": round(mistake_start, 3),
            "end": round(mistake_end, 3),
        })
        skip_until = mistake_end

    print(f"Total segments to cut: {len(cut_segments)}", file=sys.stderr)

    return {
        "cut_segments": cut_segments,
        "full_transcript": full_transcript,
        "duration": round(duration, 3),
    }


def main():
    if len(sys.argv) < 3:
        print(
            json.dumps({"error": "Usage: trigger_word_detection.py <video_path> <output_json> [model]"}),
            file=sys.stderr,
        )
        sys.exit(1)

    video_path = sys.argv[1]
    output_json_path = sys.argv[2]
    model_name = sys.argv[3] if len(sys.argv) > 3 else "base"

    if not os.path.isfile(video_path):
        result = {"error": f"Video file not found: {video_path}", "cut_segments": [], "duration": 0}
        print(json.dumps(result))
        sys.exit(1)

    try:
        result = detect_trigger_words(video_path, model_name)

        with open(output_json_path, "w") as f:
            json.dump(result, f, indent=2)

        # Print to stdout so n8n Execute Command node captures it
        print(json.dumps(result))

    except Exception as e:
        error_result = {
            "error": str(e),
            "traceback": traceback.format_exc(),
            "cut_segments": [],
            "duration": 0,
        }
        print(json.dumps(error_result))
        sys.exit(1)


if __name__ == "__main__":
    main()
