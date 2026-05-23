# AI Video Editor — Setup, Testing & Troubleshooting

## What This Does

An n8n workflow that takes a raw MP4 and automatically:

1. Removes silence gaps ≥ 0.5 s (configurable)
2. Detects and removes segments where you said "cut this" or "remove this"
3. Normalises audio to -16 LUFS with light compression and noise filtering
4. Applies colour correction (Contrast +15, Saturation -10, Warmth +3)
5. Prepends a configurable 3-second black intro with white text
6. Exports a web-ready H.264/AAC MP4

---

## System Requirements

| Requirement | Minimum |
|---|---|
| OS | Linux / macOS (Windows via WSL2) |
| RAM | 8 GB (16 GB recommended for Whisper medium/large) |
| Disk | 10 GB free per 1 GB of input video |
| CPU | Modern x86-64 (GPU optional but speeds up Whisper) |
| n8n | v0.195 or later |

---

## 1. Install Dependencies

### FFmpeg

```bash
# Ubuntu/Debian
sudo apt update && sudo apt install -y ffmpeg fontconfig

# macOS
brew install ffmpeg

# Verify
ffmpeg -version
```

### Python 3.9+

```bash
# Ubuntu/Debian
sudo apt install -y python3 python3-pip python3-venv

# macOS
brew install python
```

### Python packages

Create a virtual environment to avoid conflicts:

```bash
python3 -m venv ~/venvs/video-editor
source ~/venvs/video-editor/bin/activate

# PyTorch (CPU-only — fastest install; use GPU build if you have CUDA)
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu

# Silero VAD
pip install silero-vad

# OpenAI Whisper
pip install openai-whisper

# Deactivate when done
deactivate
```

**If you have an NVIDIA GPU**, replace the torch install line with:
```bash
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu118
```

> **Important**: In n8n Execute Command nodes the Python scripts must run with
> the virtual environment's python. Either activate it in each command or use
> the full path: `/root/venvs/video-editor/bin/python3`.

---

## 2. Folder Structure

Create this layout on your machine:

```
/your/projects/
├── ai-video-editor/
│   ├── workflow.json               ← import this into n8n
│   ├── scripts/
│   │   ├── silence_detection.py
│   │   └── trigger_word_detection.py
│   └── SETUP.md
├── input/
│   └── video.mp4                   ← drop raw videos here
└── output/                         ← edited videos appear here
```

Make scripts executable:

```bash
chmod +x /your/projects/ai-video-editor/scripts/*.py
```

---

## 3. Import the Workflow into n8n

1. Open n8n in your browser (default: `http://localhost:5678`)
2. Click **Workflows → Import from file**
3. Select `workflow.json`
4. The workflow opens with all 14 nodes connected

---

## 4. Configure File Paths

Open the **Set Variables** node and update these fields:

| Field | Description | Example |
|---|---|---|
| `inputVideoPath` | Full path to your raw MP4 | `/your/projects/input/video.mp4` |
| `outputFolder` | Folder where outputs are saved | `/your/projects/output` |
| `scriptsFolder` | Folder containing the .py scripts | `/your/projects/ai-video-editor/scripts` |
| `introText` | Text shown in the 3-second intro | `My Channel` |
| `whisperModel` | Whisper model size (see note) | `base` |
| `silenceThreshold` | Minimum silence gap to remove (seconds) | `0.5` |

**Whisper model sizes** (speed vs accuracy trade-off):

| Model | VRAM | Speed on CPU (10 min video) | Accuracy |
|---|---|---|---|
| `tiny` | ~1 GB | ~1 min | Low |
| `base` | ~1 GB | ~2 min | Good |
| `small` | ~2 GB | ~5 min | Better |
| `medium` | ~5 GB | ~15 min | High |
| `large` | ~10 GB | ~30 min | Best |

For most use-cases `base` is the best speed/accuracy balance.

**If using a virtualenv**, update the Execute Command nodes for the Python scripts
to point to the venv python, e.g.:

```
/root/venvs/video-editor/bin/python3 "{{ $('Set Variables').item.json.scriptsFolder }}/silence_detection.py" ...
```

---

## 5. Testing Procedure

### Step 1 — Quick sanity check with a 30-second test clip

```bash
# Create a test clip (requires FFmpeg)
ffmpeg -i /your/projects/input/video.mp4 -t 30 /tmp/test_clip.mp4
```

Update `inputVideoPath` in Set Variables to `/tmp/test_clip.mp4`, then click
**Execute Workflow**.

### Step 2 — Verify each stage in the n8n execution log

After running, click any node and check its **Output** tab:

| Node | What to verify |
|---|---|
| Extract Audio | `audio.wav` exists in `outputFolder`, stdout contains `AUDIO_EXTRACTED_OK` |
| Run Silence Detection | stdout is valid JSON with `speech_segments` array |
| Process VAD Results | output JSON contains `command` field with an ffmpeg call |
| Remove Silence | `silence_removed.mp4` exists in `outputFolder` |
| Run Trigger Detection | stdout is valid JSON with `cut_segments` array |
| Process Cut Points | output JSON contains `command` field |
| Cut Mistake Segments | `mistakes_removed.mp4` exists |
| Enhance Audio | stdout contains `AUDIO_ENHANCED_OK` |
| Apply Color Grading | stdout contains `COLOR_GRADED_OK` |
| Add Intro Animation | stdout contains `INTRO_ADDED_OK` |
| Final Export | stdout contains `FINAL_EXPORT_OK` |
| Return Output Path | status = `completed` |

### Step 3 — Test trigger word detection

Record a short clip where you say "cut this" mid-sentence, then say the sentence again.
Run the workflow. Open `trigger_results.json` in `outputFolder` and verify the
`cut_segments` array contains the correct timestamp.

### Step 4 — Run with full-length video

Replace `inputVideoPath` with your actual video. Typical times on a modern CPU:

| Input length | Expected total time |
|---|---|
| 5 min | ~2–4 min |
| 10 min | ~4–8 min |
| 30 min | ~12–20 min |

---

## 6. Troubleshooting Guide

### "FFmpeg not found" / `ffmpeg: command not found`

Install FFmpeg (see Section 1). If installed in a non-standard path, use the
full path in Execute Command nodes, e.g. `/usr/local/bin/ffmpeg`.

---

### "No module named 'torch'" or "No module named 'whisper'"

The Python scripts can't find the packages. Causes:

1. **Wrong Python** — n8n is calling `python3` which is the system Python, not
   the virtualenv. Fix: use the full venv path in the Execute Command command field:
   ```
   /root/venvs/video-editor/bin/python3 ...
   ```

2. **Packages not installed** — Re-run the pip install commands with the venv
   activated.

---

### "No JSON found in silence detection output"

The silence_detection.py script printed something unexpected to stdout.
In the **Run Silence Detection** node output, expand `stdout` and look for the
actual output. Common causes:

- Torch hub download progress printed to stdout (not stderr)
- Audio file path has a space — ensure paths are quoted in the command

Fix: The regex in the Code node searches for the JSON block. If the script fails
before printing JSON, the error will be in `stderr`. Switch the command to
`... 2>&1` (already included) and read the combined output.

---

### `filter_complex` error: "No such encoder 'libx264'"

FFmpeg was compiled without H.264 support. Install the full version:

```bash
# Ubuntu
sudo apt install -y ffmpeg          # includes libx264 on Ubuntu 20.04+
# If not: add ppa:mc3man/trusty-media or download a static build from ffmpeg.org
```

---

### Color grading fails: "'colortemperature' unknown filter"

The `colortemperature` filter requires FFmpeg ≥ 5.1. Check your version:

```bash
ffmpeg -version | head -1
```

If older, replace the color grading command with the equivalent using `curves`:

```
eq=contrast=1.15:saturation=0.9,curves=r='0/0 0.5/0.55 1/1':b='0/0 0.5/0.45 1/1'
```

---

### Intro animation fails: "drawtext: no such filter"

FFmpeg needs `--enable-libfreetype` at compile time. Check:

```bash
ffmpeg -filters 2>&1 | grep drawtext
```

If missing, install `libfreetype6-dev` and recompile, or use a static FFmpeg
build from ffmpeg.org.

---

### Whisper model download hangs or fails

The Whisper model is downloaded from the internet on first use (~150 MB for
`base`). If behind a proxy:

```bash
export HTTPS_PROXY=http://your-proxy:port
```

To pre-download manually:

```python
import whisper
whisper.load_model("base")
```

---

### "Could not write header for output" / codec errors

Check that your input video has both a video and audio stream:

```bash
ffprobe -v error -show_streams your_video.mp4
```

If audio is missing, the filter_complex commands will fail on the audio streams.
For video-only files, remove all audio-related parts from the filter (`[0:a]`, etc.)
and map only `[outv]`.

---

### Workflow timeout for large files

n8n's default execution timeout is 1 hour. For long videos increase it:

In `~/.n8n/config` (or `n8n/config` in your Docker volume):
```json
{
  "executions": {
    "timeout": 3600,
    "timeoutMax": 7200
  }
}
```

---

### Output video has wrong resolution

The intro animation node hardcodes `1920x1080`. If your video is a different
resolution, update the `color=c=black:s=1920x1080` filter in the
**Add Intro Animation** node to match your video's dimensions. You can detect
the resolution automatically by adding an FFprobe step before that node.

---

## Intermediate Files Reference

All intermediate files are saved in `outputFolder`:

| File | Created by |
|---|---|
| `audio.wav` | Extract Audio |
| `silence_results.json` | Run Silence Detection |
| `silence_removed.mp4` | Remove Silence |
| `trigger_results.json` | Run Trigger Detection |
| `mistakes_removed.mp4` | Cut Mistake Segments |
| `audio_enhanced.mp4` | Enhance Audio |
| `color_graded.mp4` | Apply Color Grading |
| `with_intro.mp4` | Add Intro Animation |
| `<input_name>_edited.mp4` | Final Export (deliverable) |

To save disk space, delete the intermediates after confirming the output is good:

```bash
cd /your/projects/output
rm audio.wav silence_results.json silence_removed.mp4 \
   trigger_results.json mistakes_removed.mp4 audio_enhanced.mp4 \
   color_graded.mp4 with_intro.mp4
```
