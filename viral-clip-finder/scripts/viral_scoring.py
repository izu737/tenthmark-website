"""
Claude API integration for viral potential analysis of transcript segments.
Scores each segment on 8 criteria (0-10 each) and returns a composite score.
"""

import os
import json
import sys
import time
from dataclasses import dataclass, asdict

import anthropic


SCORING_CRITERIA = [
    "hook_strength",
    "emotional_intensity",
    "information_density",
    "standalone_value",
    "cta_potential",
    "controversy",
    "relatability",
    "quotability",
]

SYSTEM_PROMPT = """\
You are an expert viral content analyst specialising in short-form video for TikTok, Instagram Reels, and YouTube Shorts.
You evaluate transcript segments and score their viral potential across 8 criteria.
Always respond with valid JSON matching the exact schema provided.
"""

ANALYSIS_PROMPT = """\
Analyse this transcript segment for viral short-form video potential.

Segment:
Start: {start}s | End: {end}s | Duration: {duration}s
Text: \"\"\"{text}\"\"\"

Score each criterion from 0 (very low) to 10 (exceptional):

1. hook_strength      – Does it open with a compelling hook that grabs attention in the first 3 seconds?
2. emotional_intensity – Does it evoke strong emotion (surprise, curiosity, anger, inspiration, humour)?
3. information_density – Does it deliver high-value insights quickly?
4. standalone_value   – Can it be fully understood without the full video?
5. cta_potential      – Does it naturally create curiosity to watch more?
6. controversy        – Does it present a strong, contrarian, or polarising viewpoint?
7. relatability       – Will the target audience see themselves in this moment?
8. quotability        – Does it contain memorable one-liners or shareable phrases?

Also provide:
- suggested_title: A punchy, clickbait-style title (max 60 chars)
- hook_text: A 5-10 word opening hook overlay text for the first 3 seconds
- reason: One sentence explaining the top viral driver

Respond with ONLY this JSON structure:
{{
  "hook_strength": <int>,
  "emotional_intensity": <int>,
  "information_density": <int>,
  "standalone_value": <int>,
  "cta_potential": <int>,
  "controversy": <int>,
  "relatability": <int>,
  "quotability": <int>,
  "suggested_title": "<string>",
  "hook_text": "<string>",
  "reason": "<string>"
}}
"""


@dataclass
class ScoredSegment:
    start: float
    end: float
    text: str
    hook_strength: int = 0
    emotional_intensity: int = 0
    information_density: int = 0
    standalone_value: int = 0
    cta_potential: int = 0
    controversy: int = 0
    relatability: int = 0
    quotability: int = 0
    composite_score: float = 0.0
    suggested_title: str = ""
    hook_text: str = ""
    reason: str = ""
    error: str = ""


# Weights for composite score (must sum to 1.0)
WEIGHTS = {
    "hook_strength": 0.20,
    "emotional_intensity": 0.18,
    "information_density": 0.12,
    "standalone_value": 0.15,
    "cta_potential": 0.10,
    "controversy": 0.10,
    "relatability": 0.10,
    "quotability": 0.05,
}


def compute_composite(scores: dict) -> float:
    total = sum(scores.get(k, 0) * w for k, w in WEIGHTS.items())
    return round(total * 10, 1)  # scale to 0-100


def analyse_segment(
    client: anthropic.Anthropic,
    segment: dict,
    model: str = "claude-haiku-4-5-20251001",
    max_retries: int = 3,
) -> ScoredSegment:
    """Call Claude to score a single transcript segment."""
    start = segment.get("start", 0)
    end = segment.get("end", 0)
    text = segment.get("text", "").strip()
    duration = round(end - start, 1)

    seg = ScoredSegment(start=start, end=end, text=text)

    prompt = ANALYSIS_PROMPT.format(start=start, end=end, duration=duration, text=text)

    for attempt in range(max_retries):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=512,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            data = json.loads(raw)

            for criterion in SCORING_CRITERIA:
                setattr(seg, criterion, int(data.get(criterion, 0)))

            seg.composite_score = compute_composite(
                {c: getattr(seg, c) for c in SCORING_CRITERIA}
            )
            seg.suggested_title = data.get("suggested_title", "")
            seg.hook_text = data.get("hook_text", "")
            seg.reason = data.get("reason", "")
            return seg

        except (json.JSONDecodeError, KeyError) as e:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            else:
                seg.error = str(e)

    return seg


def score_all_segments(
    segments: list[dict],
    api_key: str | None = None,
    model: str = "claude-haiku-4-5-20251001",
    top_n: int = 10,
    min_duration: float = 25.0,
    max_duration: float = 95.0,
) -> list[ScoredSegment]:
    """
    Score all segments, filter by duration, return top_n sorted by composite score.
    """
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ValueError("ANTHROPIC_API_KEY not set")

    client = anthropic.Anthropic(api_key=key)

    # Filter by duration
    valid = [
        s for s in segments
        if min_duration <= (s.get("end", 0) - s.get("start", 0)) <= max_duration
    ]
    print(f"Scoring {len(valid)} segments (filtered from {len(segments)})...")

    scored = []
    for i, seg in enumerate(valid):
        print(f"  [{i + 1}/{len(valid)}] {seg.get('start', 0):.1f}s - {seg.get('end', 0):.1f}s")
        result = analyse_segment(client, seg, model=model)
        scored.append(result)
        time.sleep(0.3)  # gentle rate limiting

    scored.sort(key=lambda s: s.composite_score, reverse=True)

    # Diversity check: avoid clustering from same section
    diverse = _diversity_filter(scored, top_n=top_n)
    return diverse


def _diversity_filter(
    scored: list[ScoredSegment],
    top_n: int = 10,
    min_gap: float = 30.0,
) -> list[ScoredSegment]:
    """Ensure selected clips don't overlap within min_gap seconds."""
    selected = []
    for seg in scored:
        overlaps = any(
            not (seg.end + min_gap < s.start or seg.start > s.end + min_gap)
            for s in selected
        )
        if not overlaps:
            selected.append(seg)
        if len(selected) >= top_n:
            break
    return selected


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python viral_scoring.py <transcript_json> [top_n] [output_json]")
        print("  transcript_json: output from subtitle_generation.py")
        sys.exit(1)

    tpath = sys.argv[1]
    top_n = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    opath = sys.argv[3] if len(sys.argv) > 3 else None

    with open(tpath) as f:
        segments = json.load(f)

    results = score_all_segments(segments, top_n=top_n)

    output = [asdict(r) for r in results]

    if opath:
        with open(opath, "w") as f:
            json.dump(output, f, indent=2)
        print(f"Saved {len(output)} scored segments to {opath}")
    else:
        print(json.dumps(output, indent=2))
