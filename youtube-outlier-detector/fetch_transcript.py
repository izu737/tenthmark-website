#!/usr/bin/env python3
"""
Fetch YouTube video transcript and output JSON to stdout.
Usage: python3 fetch_transcript.py <video_id_or_url>

Install dependency: pip install youtube-transcript-api
"""

import sys
import json
import urllib.parse


def extract_video_id(input_str: str) -> str:
    input_str = input_str.strip()
    if "youtu.be" in input_str:
        return input_str.split("youtu.be/")[-1].split("?")[0].split("&")[0]
    if "youtube.com" in input_str:
        parsed = urllib.parse.urlparse(input_str)
        params = urllib.parse.parse_qs(parsed.query)
        return params.get("v", [""])[0]
    return input_str


def fetch_transcript(video_id: str) -> dict:
    try:
        from youtube_transcript_api import (
            YouTubeTranscriptApi,
            TranscriptsDisabled,
            NoTranscriptFound,
        )
    except ImportError:
        return {
            "success": False,
            "error": "youtube-transcript-api not installed. Run: pip install youtube-transcript-api",
            "video_id": video_id,
            "transcript": "",
            "word_count": 0,
            "language": "",
        }

    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

        transcript = None
        # Prefer manually created English transcripts
        for lang in ["en", "en-US", "en-GB", "en-CA"]:
            try:
                transcript = transcript_list.find_manually_created_transcript([lang])
                break
            except Exception:
                continue

        # Fall back to auto-generated English
        if transcript is None:
            try:
                transcript = transcript_list.find_generated_transcript(["en"])
            except Exception:
                pass

        # Fall back to any transcript and translate to English
        if transcript is None:
            all_transcripts = list(transcript_list)
            if all_transcripts:
                try:
                    transcript = all_transcripts[0].translate("en")
                except Exception:
                    transcript = all_transcripts[0]

        if transcript is None:
            return {
                "success": False,
                "error": "No transcript available for this video",
                "video_id": video_id,
                "transcript": "",
                "word_count": 0,
                "language": "",
            }

        entries = transcript.fetch()
        full_text = " ".join(e["text"].strip() for e in entries if e.get("text"))

        # Trim to ~8 000 words to stay within API context limits
        words = full_text.split()
        truncated = False
        if len(words) > 8000:
            words = words[:8000]
            truncated = True
        full_text = " ".join(words)
        if truncated:
            full_text += " [transcript truncated]"

        return {
            "success": True,
            "video_id": video_id,
            "transcript": full_text,
            "word_count": len(words),
            "language": transcript.language_code,
            "truncated": truncated,
        }

    except TranscriptsDisabled:
        return {
            "success": False,
            "error": "Transcripts are disabled for this video",
            "video_id": video_id,
            "transcript": "",
            "word_count": 0,
            "language": "",
        }
    except NoTranscriptFound:
        return {
            "success": False,
            "error": "No transcript found",
            "video_id": video_id,
            "transcript": "",
            "word_count": 0,
            "language": "",
        }
    except Exception as exc:
        return {
            "success": False,
            "error": str(exc),
            "video_id": video_id,
            "transcript": "",
            "word_count": 0,
            "language": "",
        }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(
            json.dumps(
                {
                    "success": False,
                    "error": "Usage: python3 fetch_transcript.py <video_id_or_url>",
                    "transcript": "",
                }
            )
        )
        sys.exit(1)

    raw_input = sys.argv[1]
    vid = extract_video_id(raw_input)

    if not vid:
        print(
            json.dumps(
                {
                    "success": False,
                    "error": f"Could not extract video ID from: {raw_input}",
                    "transcript": "",
                }
            )
        )
        sys.exit(1)

    result = fetch_transcript(vid)
    print(json.dumps(result, ensure_ascii=False))
