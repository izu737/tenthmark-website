# AI Thumbnail Generator — Setup Guide

## Overview
n8n workflow that swaps your face into any YouTube or custom thumbnail using the Replicate API (`yan-ops/face-swap`). Generates 3 variations per input, with optional OCR text replacement.

---

## 1. Reference Photo Preparation

Create `reference_photos/` inside this folder and add photos named exactly as follows:

| Filename | Angle description |
|---|---|
| `front_center.jpg` | Looking straight at camera, 0° yaw, 0° pitch |
| `left_15.jpg` | Turned 15° to your left |
| `left_30.jpg` | Turned 30° to your left |
| `right_15.jpg` | Turned 15° to your right |
| `right_30.jpg` | Turned 30° to your right |
| `tilt_up_15.jpg` | Chin slightly up, 15° pitch |
| `tilt_down_15.jpg` | Chin slightly down, 15° pitch |
| `left_15_up_10.jpg` | Left 15°, chin up 10° |
| `right_15_up_10.jpg` | Right 15°, chin up 10° |

**Photo requirements:**
- Face clearly visible, well-lit, neutral expression
- Minimum 512×512 px, ideally 1080×1080 px
- JPEG format
- No glasses, hats, or heavy obstructions

---

## 2. API Key Setup

### Replicate API
1. Sign up at https://replicate.com
2. Go to Account → API tokens → Create token
3. Set environment variable: `export REPLICATE_API_KEY=your_token_here`
4. Or in n8n: Settings → Credentials → New → Header Auth
   - Name: `Authorization`
   - Value: `Token your_token_here`

---

## 3. Dependencies

Install Python dependencies:

```bash
pip install mediapipe opencv-python pytesseract pillow numpy
```

Install system packages (Ubuntu/Debian):

```bash
sudo apt-get install tesseract-ocr tesseract-ocr-eng imagemagick
```

Verify installations:

```bash
python3 -c "import mediapipe; print('MediaPipe OK')"
python3 -c "import pytesseract; print(pytesseract.get_tesseract_version())"
```

---

## 4. n8n Setup

1. Open n8n (http://localhost:5678 by default)
2. Click **Import from file** and select `n8n-workflow.json`
3. Update the **Set Variables** node:
   - Set `outputFolder` to your desired output path
   - Set `referencePhotosFolder` to the absolute path of `reference_photos/`
4. In the three **Replicate Face Swap** nodes, set the Authorization header to your Replicate API token
5. Activate the workflow (toggle in top-right)

---

## 5. Testing Procedure

### Step 1 — Test face detection script
```bash
python3 scripts/face_detection.py "https://img.youtube.com/vi/dQw4w9WgXcQ/maxresdefault.jpg" ./output
# Expected output: {"yaw": float, "pitch": float, "roll": float, "face_detected": true}
```

### Step 2 — Test OCR text replacement
```bash
python3 scripts/text_replacement.py "https://img.youtube.com/vi/dQw4w9WgXcQ/maxresdefault.jpg" ./output "My New Title"
# Expected output: {"text_regions": [...], "output_path": "...", "success": true}
```

### Step 3 — Test full workflow via webhook
```bash
# After activating the n8n workflow:
curl -X POST http://localhost:5678/webhook/thumbnail-generator \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}'
```

### Step 4 — Test with a direct image URL
```bash
curl -X POST http://localhost:5678/webhook/thumbnail-generator \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/my-thumbnail.jpg"}'
```

### Expected response format
```json
{
  "status": "success",
  "thumbnails": [
    {"variation": 1, "url": "https://replicate.delivery/...", "localPath": "output/thumbnail_v1_1700000000.jpg"},
    {"variation": 2, "url": "https://replicate.delivery/...", "localPath": "output/thumbnail_v2_1700000000.jpg"},
    {"variation": 3, "url": "https://replicate.delivery/...", "localPath": "output/thumbnail_v3_1700000000.jpg"}
  ],
  "generatedAt": 1700000000
}
```

---

## 6. Cost Estimation (Replicate API)

The `yan-ops/face-swap` model on Replicate is billed per prediction run.

| Item | Cost (approx.) |
|---|---|
| Per face-swap prediction | ~$0.005 – $0.010 USD |
| 3 variations per thumbnail | ~$0.015 – $0.030 USD |
| 100 thumbnails/month | ~$1.50 – $3.00 USD |
| 1,000 thumbnails/month | ~$15 – $30 USD |

> Costs vary slightly based on image resolution and model cold-start. 1920×1080 images may cost slightly more than smaller sizes.

**Time per generation:** 15–45 seconds per variation (3 run in parallel → total wall time ~45 seconds, within the 60-second limit).

---

## 7. File Structure

```
thumbnail-generator/
├── n8n-workflow.json          # Import this into n8n
├── setup.md                   # This file
├── scripts/
│   ├── face_detection.py      # MediaPipe face angle analysis
│   └── text_replacement.py    # Tesseract OCR + PIL text replacement
├── reference_photos/          # Add your reference photos here
│   ├── front_center.jpg
│   ├── left_15.jpg
│   └── ...
└── output/                    # Generated thumbnails saved here
```
