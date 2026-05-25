# Setup Instructions – AI Viral Clip Finder

## Prerequisites

- Python 3.11+
- FFmpeg 6.0+ with libx264 and loudnorm filter
- Node.js 18+ (for n8n)
- 4 GB RAM minimum; 8 GB recommended for local Whisper
- Disk space: ~500 MB per hour of source video (temporary files)

---

## 1. Folder Structure

```
viral-clip-finder/
├── n8n/
│   └── workflow.json          # Import this into n8n
├── scripts/
│   ├── speaker_detection.py   # OpenCV face tracking & crop box
│   ├── subtitle_generation.py # Whisper transcription + SRT/ASS output
│   ├── thumbnail_creation.py  # Best-frame extraction + text overlay
│   ├── viral_scoring.py       # Claude API scoring
│   └── clip_generator.py      # FFmpeg pipeline orchestrator
├── docs/
│   ├── ffmpeg_commands.md
│   ├── setup_instructions.md
│   ├── testing_procedure.md
│   └── cost_estimation.md
├── requirements.txt
└── .env.example
```

Mount these paths inside n8n:
- Scripts → `/app/scripts/`
- Input video → `/data/input/`
- Output → `/data/output/`

---

## 2. System Dependencies

### Ubuntu / Debian

```bash
sudo apt update && sudo apt install -y \
  ffmpeg \
  python3-pip python3-venv \
  libopencv-dev python3-opencv \
  fonts-dejavu-core \
  bc
```

### macOS (Homebrew)

```bash
brew install ffmpeg python@3.11 opencv
```

### Verify FFmpeg

```bash
ffmpeg -version | head -1
ffmpeg -filters | grep loudnorm   # must show loudnorm
```

---

## 3. Python Environment

```bash
cd viral-clip-finder
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

`requirements.txt`:
```
anthropic>=0.40.0
openai>=1.50.0
opencv-python>=4.9.0
Pillow>=10.4.0
moviepy>=1.0.3
pysrt>=1.1.2
numpy>=1.26.0
openai-whisper>=20240930          # local Whisper only
```

---

## 4. API Keys

Copy `.env.example` to `.env` and fill in your keys:

```bash
cp .env.example .env
```

`.env.example`:
```env
# Required
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...             # for Whisper API

# Optional
WHISPER_MODEL=base                # base / small / medium / large
TARGET_LUFS=-14                   # audio normalisation target
CHANNEL_NAME=Watch Full Video     # CTA text
MUSIC_PATH=                       # leave empty to skip music bed
```

---

## 5. n8n Setup

### Install n8n

```bash
npm install -g n8n
```

### Configure credentials

In n8n → Settings → Credentials:

1. **HTTP Header Auth** (Anthropic)
   - Name: `Anthropic API`
   - Header name: `x-api-key`
   - Header value: `<your ANTHROPIC_API_KEY>`

2. **HTTP Header Auth** (OpenAI / Whisper)
   - Name: `OpenAI API`
   - Header name: `Authorization`
   - Header value: `Bearer <your OPENAI_API_KEY>`

### Import the workflow

1. Open n8n → Workflows → Import
2. Select `n8n/workflow.json`
3. Update node `Set Variables` → `VIDEO_PATH` and `OUTPUT_DIR`
4. Activate the workflow

### Environment variables for n8n

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...
n8n start
```

Or add to your n8n `docker-compose.yml`:
```yaml
environment:
  - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
  - OPENAI_API_KEY=${OPENAI_API_KEY}
```

---

## 6. Docker Setup (recommended for production)

```dockerfile
# Dockerfile
FROM n8nio/n8n:latest

USER root
RUN apk add --no-cache ffmpeg python3 py3-pip opencv bc font-dejavu

COPY requirements.txt /tmp/
RUN pip3 install -r /tmp/requirements.txt

COPY scripts/ /app/scripts/
RUN chmod +x /app/scripts/*.py

USER node
```

```yaml
# docker-compose.yml
version: "3.8"
services:
  n8n:
    build: .
    ports:
      - "5678:5678"
    volumes:
      - ./data:/data
      - n8n_data:/home/node/.n8n
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - N8N_HOST=localhost
      - N8N_PORT=5678
volumes:
  n8n_data:
```

```bash
docker compose up -d
```

---

## 7. Standalone Python (without n8n)

```bash
# Full pipeline in one command
source .venv/bin/activate
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...

# Step 1: Generate transcript
python3 scripts/subtitle_generation.py \
  /data/input/video.mp4 \
  /data/output/subs \
  $OPENAI_API_KEY

# Step 2: Score segments
python3 scripts/viral_scoring.py \
  /data/output/subs/video_transcript.json \
  10 \
  /data/output/scored_segments.json

# Step 3: Detect speaker crop
python3 scripts/speaker_detection.py \
  /data/input/video.mp4 \
  /data/output/crop_data.json

# Step 4: Generate clips
python3 scripts/clip_generator.py \
  /data/input/video.mp4 \
  /data/output/scored_segments.json \
  /data/output/clips \
  "Watch Full Video"

# Step 5: Generate thumbnails
python3 scripts/thumbnail_creation.py \
  /data/input/video.mp4 \
  /data/output/scored_segments.json \
  /data/output/thumbnails
```

---

## 8. Permissions

The scripts write to `OUTPUT_DIR`. Ensure the directory is writable:

```bash
mkdir -p /data/input /data/output
chmod 755 /data/output
```

n8n's Execute Command node runs as the n8n process user. Ensure that user has access to `ffmpeg`, `ffprobe`, and the Python scripts.
