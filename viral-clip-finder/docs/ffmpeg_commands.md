# FFmpeg Command Reference – Viral Clip Finder

All commands target **1080×1920 (9:16)** output for TikTok / Reels / Shorts.

---

## 1. Video Validation & Metadata

```bash
ffprobe -v error \
  -show_entries format=duration,size,bit_rate \
  -show_entries stream=width,height,r_frame_rate,codec_name,codec_type \
  -of json \
  input.mp4
```

---

## 2. Audio Extraction (for Whisper)

```bash
ffmpeg -i input.mp4 \
  -vn -ar 16000 -ac 1 -f wav \
  audio.wav
```

> Whisper performs best on mono 16 kHz WAV.

---

## 3. Clip Extraction (lossless copy)

```bash
ffmpeg -ss 45.2 -i input.mp4 \
  -t 62.8 \
  -c copy -avoid_negative_ts make_zero \
  raw_clip.mp4
```

> `-ss` before `-i` is fast input seeking. `-t` is duration, not end time.

---

## 4. 9:16 Smart Crop + Scale

```bash
# Static crop (recommended for talking-head videos)
ffmpeg -i raw_clip.mp4 \
  -vf "crop=608:1080:336:0,scale=1080:1920:flags=lanczos" \
  -c:v libx264 -preset fast -crf 22 -c:a copy \
  cropped_clip.mp4

# Dynamic crop with speaker tracking (use crop_boxes from speaker_detection.py)
# Build a sendcmd file or use the Python script instead
```

Crop formula for a 1920×1080 source centered on speaker at x=760:
```
crop_w = int(1080 * 9/16) = 608
crop_x = max(0, min(760 - 304, 1920 - 608)) = 456
crop_h = 1080
crop_y = 0
scale   = 1080:1920
```

---

## 5. Subtitle Burning (ASS format)

```bash
ffmpeg -i cropped_clip.mp4 \
  -vf "ass=subtitles.ass" \
  -c:v libx264 -preset fast -crf 22 -c:a copy \
  subbed_clip.mp4
```

For SRT (simpler, no animation):
```bash
ffmpeg -i cropped_clip.mp4 \
  -vf "subtitles=subtitles.srt:force_style='FontName=Arial,FontSize=22,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,Outline=3,Alignment=2'" \
  -c:v libx264 -preset fast -crf 22 -c:a copy \
  subbed_clip.mp4
```

---

## 6. Hook Text Overlay (first 3 seconds)

```bash
ffmpeg -i subbed_clip.mp4 \
  -vf "drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:\
text='You WON\\'T Believe This':fontsize=64:fontcolor=white:\
borderw=4:bordercolor=black:x=(w-text_w)/2:y=(h*0.08):\
enable='between(t,0,3)'" \
  -c:v libx264 -preset fast -crf 22 -c:a copy \
  hooked_clip.mp4
```

> Use `\\'` to escape apostrophes in the drawtext filter.

---

## 7. CTA End Screen (last 3 seconds)

```bash
# Get duration first
DURATION=$(ffprobe -v error -show_entries format=duration \
  -of default=noprint_wrappers=1:nokey=1 hooked_clip.mp4)
CTA_START=$(echo "$DURATION - 3" | bc)

ffmpeg -i hooked_clip.mp4 \
  -vf "drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:\
text='Watch full video →':fontsize=56:fontcolor=white:\
borderw=4:bordercolor=black:x=(w-text_w)/2:y=(h*0.78):\
enable='between(t,${CTA_START},${DURATION})',\
drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:\
text='@YourChannel':fontsize=40:fontcolor=#FFD700:\
borderw=3:bordercolor=black:x=(w-text_w)/2:y=(h*0.84):\
enable='between(t,${CTA_START},${DURATION})'" \
  -c:v libx264 -preset fast -crf 22 -c:a copy \
  cta_clip.mp4
```

---

## 8. Audio Normalisation (Two-Pass Loudnorm)

**Pass 1 – Measure:**
```bash
ffmpeg -i cta_clip.mp4 \
  -af "loudnorm=I=-14:TP=-2:LRA=11:print_format=json" \
  -f null - 2>&1 | tail -20
```

**Pass 2 – Apply (substitute measured values):**
```bash
ffmpeg -i cta_clip.mp4 \
  -af "loudnorm=I=-14:TP=-2:LRA=11:\
measured_I=-18.3:measured_TP=-4.1:measured_LRA=7.2:\
measured_thresh=-29.1:offset=0.5:linear=true:print_format=none" \
  -c:v copy \
  normalised_clip.mp4
```

---

## 9. Background Music Bed

```bash
ffmpeg -i normalised_clip.mp4 \
  -stream_loop -1 -i background_music.mp3 \
  -filter_complex "[1:a]volume=0.08[bg];[0:a][bg]amix=inputs=2:duration=first[aout]" \
  -map 0:v -map "[aout]" \
  -c:v copy -c:a aac -b:a 192k \
  final_clip.mp4
```

---

## 10. Thumbnail Extraction

```bash
# Extract frame at 20% into clip (usually best expression)
DURATION=$(ffprobe -v error -show_entries format=duration \
  -of default=noprint_wrappers=1:nokey=1 final_clip.mp4)
THUMB_T=$(echo "$DURATION * 0.20" | bc)

ffmpeg -ss $THUMB_T -i final_clip.mp4 \
  -vframes 1 -q:v 2 \
  thumbnail.jpg
```

---

## 11. Batch Export (5-7 clips)

```bash
#!/bin/bash
# batch_export.sh
SEGMENTS=(
  "10.5 72.3"
  "85.0 148.2"
  "200.1 261.5"
  "315.0 378.8"
  "420.5 485.0"
)

for i in "${!SEGMENTS[@]}"; do
  read START END <<< "${SEGMENTS[$i]}"
  DUR=$(echo "$END - $START" | bc)
  ffmpeg -y -ss $START -i input.mp4 \
    -t $DUR -c copy -avoid_negative_ts make_zero \
    "clip_$((i+1)).mp4"
done
```

---

## 12. Quality Presets

| Use Case          | Preset    | CRF | Expected Size |
|-------------------|-----------|-----|---------------|
| Draft preview     | ultrafast | 28  | ~8 MB/min     |
| Standard publish  | fast      | 22  | ~25 MB/min    |
| High quality      | slow      | 18  | ~60 MB/min    |
| Archive master    | veryslow  | 15  | ~120 MB/min   |

---

## 13. Hardware Acceleration (optional)

```bash
# NVIDIA NVENC
ffmpeg -hwaccel cuda -i input.mp4 \
  -vf "crop=608:1080:336:0,scale=1080:1920" \
  -c:v h264_nvenc -preset fast -cq 22 \
  output.mp4

# Apple VideoToolbox (macOS)
ffmpeg -i input.mp4 \
  -vf "crop=608:1080:336:0,scale=1080:1920" \
  -c:v h264_videotoolbox -b:v 8M \
  output.mp4
```
