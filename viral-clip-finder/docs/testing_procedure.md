# Testing Procedure – AI Viral Clip Finder

Use this procedure after setup to verify every stage of the pipeline works correctly before processing a real video.

---

## 1. Create a Sample Test Video

If you don't have a test video, generate a 90-second synthetic one with FFmpeg:

```bash
ffmpeg -f lavfi \
  -i "testsrc2=size=1920x1080:rate=30:duration=90" \
  -f lavfi -i "sine=frequency=440:sample_rate=44100" \
  -c:v libx264 -preset ultrafast -crf 30 \
  -c:a aac -b:a 128k -shortest \
  /data/input/test_video.mp4
```

For a more realistic test, download a public-domain YouTube video:
```bash
# Using yt-dlp (install: pip install yt-dlp)
yt-dlp -f "bestvideo[height<=1080]+bestaudio/best[height<=1080]" \
  --merge-output-format mp4 \
  -o "/data/input/test_video.mp4" \
  "https://www.youtube.com/watch?v=<PUBLIC_DOMAIN_VIDEO_ID>"
```

---

## 2. Validate FFmpeg Installation

```bash
# Should print version ≥ 6.0
ffmpeg -version | head -1

# Test crop filter
ffmpeg -f lavfi -i testsrc2=size=1920x1080:rate=1:duration=1 \
  -vf "crop=608:1080:656:0,scale=1080:1920" \
  -vframes 1 /tmp/crop_test.jpg && echo "CROP: OK"

# Test loudnorm
ffmpeg -f lavfi -i "sine=frequency=440:duration=5" \
  -af "loudnorm=I=-14:TP=-2:LRA=11:print_format=none" \
  -f null - && echo "LOUDNORM: OK"

# Test drawtext
ffmpeg -f lavfi -i testsrc2=size=1080x1920:rate=1:duration=1 \
  -vf "drawtext=text='Test Hook':fontsize=64:fontcolor=white:x=(w-text_w)/2:y=80" \
  -vframes 1 /tmp/drawtext_test.jpg && echo "DRAWTEXT: OK"
```

---

## 3. Test Speaker Detection

```bash
source .venv/bin/activate

python3 scripts/speaker_detection.py \
  /data/input/test_video.mp4 \
  /tmp/crop_data.json

# Expected output:
# Resolution : 1920x1080
# Duration   : 90.0s
# Dominant crop: {'x': <int>, 'y': 0, 'w': 608, 'h': 1080}
# FFmpeg filter: crop=608:1080:<x>:0,scale=1080:1920:flags=lanczos

cat /tmp/crop_data.json | python3 -c "import sys,json; d=json.load(sys.stdin); print('SPEAKER DETECTION: OK' if 'dominant_crop' in d else 'FAIL')"
```

---

## 4. Test Subtitle Generation (Whisper API)

```bash
# Requires OPENAI_API_KEY
export OPENAI_API_KEY=sk-...

python3 scripts/subtitle_generation.py \
  /data/input/test_video.mp4 \
  /tmp/subs_test \
  $OPENAI_API_KEY

# Expected files:
ls /tmp/subs_test/
# test_video.srt
# test_video.ass
# test_video_transcript.json

python3 -c "
import json
with open('/tmp/subs_test/test_video_transcript.json') as f:
    segs = json.load(f)
print(f'WHISPER: OK — {len(segs)} segments transcribed')
print(f'Sample: {segs[0] if segs else \"(empty)\"}')
"
```

**Local Whisper fallback (no API key):**
```bash
python3 -c "
from scripts.subtitle_generation import transcribe_whisper_local, generate_subtitles
segs = transcribe_whisper_local('/tmp/audio.wav', model_size='base')
print(f'Local Whisper: OK — {len(segs)} segments')
"
```

---

## 5. Test Viral Scoring (Claude API)

```bash
export ANTHROPIC_API_KEY=sk-ant-...

# Create a mock transcript for testing
cat > /tmp/test_segments.json << 'EOF'
[
  {"start": 0, "end": 45, "text": "I discovered a secret that 99% of people never learn. Here is exactly how I went from zero to a million subscribers in 30 days."},
  {"start": 50, "end": 90, "text": "Most people think they need fancy equipment to go viral but that is completely wrong. Your phone is all you need."}
]
EOF

python3 scripts/viral_scoring.py \
  /tmp/test_segments.json \
  2 \
  /tmp/scored_test.json

python3 -c "
import json
with open('/tmp/scored_test.json') as f:
    segs = json.load(f)
for s in segs:
    print(f'Score: {s[\"composite_score\"]} | {s[\"suggested_title\"]}')
print('VIRAL SCORING: OK' if segs else 'FAIL')
"
```

Expected: Two scored segments, each with `composite_score` 0–100, `suggested_title`, `hook_text`, and `reason`.

---

## 6. Test Clip Generator (FFmpeg Pipeline)

```bash
# Create minimal scored segments file
cat > /tmp/test_scored.json << 'EOF'
[
  {"start": 5.0, "end": 35.0, "composite_score": 72, "suggested_title": "Test Clip One",
   "hook_text": "You won't believe this", "hook_strength": 8, "emotional_intensity": 7}
]
EOF

python3 scripts/clip_generator.py \
  /data/input/test_video.mp4 \
  /tmp/test_scored.json \
  /tmp/clips_test \
  "My Channel"

ls -lh /tmp/clips_test/*.mp4
# Expected: clip_01_score72.mp4, ~5-15 MB

# Verify dimensions
ffprobe -v error \
  -show_entries stream=width,height \
  -of default=noprint_wrappers=1 \
  /tmp/clips_test/clip_01_score72.mp4
# Expected: width=1080, height=1920
```

---

## 7. Test Thumbnail Generation

```bash
python3 scripts/thumbnail_creation.py \
  /data/input/test_video.mp4 \
  /tmp/test_scored.json \
  /tmp/thumbnails_test

ls -lh /tmp/thumbnails_test/*.jpg
# Expected: test_video_thumb_01.jpg

# Verify thumbnail dimensions
ffprobe -v error \
  -show_entries stream=width,height \
  -of default=noprint_wrappers=1 \
  /tmp/thumbnails_test/test_video_thumb_01.jpg
# Expected: width=1080, height=1920
```

---

## 8. End-to-End n8n Workflow Test

1. Place `test_video.mp4` in your configured `INPUT_DIR`
2. Open n8n → Import `n8n/workflow.json`
3. Update `Set Variables` node:
   - `VIDEO_PATH` → `/data/input/test_video.mp4`
   - `OUTPUT_DIR` → `/data/output/test_run`
4. Click **Execute Workflow**
5. Monitor execution — each node should turn green
6. Check output:
   ```bash
   ls -lh /data/output/test_run/
   # Expected:
   # audio.wav
   # crop_data.json
   # subs/
   # clips/
   # thumbnails/
   # final_manifest.json
   ```
7. Trigger user selection webhook:
   ```bash
   curl -X POST http://localhost:5678/webhook/viral-clip-selection \
     -H "Content-Type: application/json" \
     -d '{"clip_ids": [1, 2, 3]}'
   ```
8. Verify `final_manifest.json` contains selected clips.

---

## 9. Smoke Test Checklist

| Test | Command | Expected Result |
|------|---------|-----------------|
| FFmpeg installed | `ffmpeg -version` | Version ≥ 6.0 |
| Crop filter | See §2 | `CROP: OK` |
| Loudnorm | See §2 | `LOUDNORM: OK` |
| Speaker detection | §3 | JSON with `dominant_crop` |
| Whisper API | §4 | ≥ 1 transcript segment |
| Claude scoring | §5 | Scores 0-100, titles generated |
| Clip generation | §6 | 1080×1920 MP4 output |
| Thumbnail | §7 | 1080×1920 JPG output |
| n8n workflow | §8 | `final_manifest.json` created |

All tests passing = system is ready for production video.
