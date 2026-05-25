# Cost Estimation – AI Viral Clip Finder

Costs per **one 10-minute video** processed (industry-standard pricing as of May 2026).

---

## API Cost Breakdown

### Whisper API (OpenAI)

| Item | Detail | Cost |
|------|--------|------|
| Audio transcription | 10 min @ $0.006/min | **$0.06** |

### Claude API (Anthropic) — Viral Scoring

Each segment analysis uses ~400 input tokens + ~200 output tokens.
With 50 sliding-window segments from a 10-minute video:

| Item | Tokens | Rate | Cost |
|------|--------|------|------|
| Input (50 × 400) | 20,000 | $0.80/MTok (Haiku 4.5) | **$0.016** |
| Output (50 × 200) | 10,000 | $4.00/MTok (Haiku 4.5) | **$0.040** |
| **Claude subtotal** | | | **$0.056** |

> Using `claude-haiku-4-5-20251001` for scoring keeps costs low.
> Switch to `claude-sonnet-4-6` (~8× more expensive) for higher scoring quality.

### Total API Cost per Video

| Service | Cost |
|---------|------|
| OpenAI Whisper | $0.060 |
| Anthropic Claude (Haiku) | $0.056 |
| **Total per video** | **~$0.12** |

---

## Compute Cost

### Self-hosted (VPS / cloud VM)

| Processing Stage | CPU Time | Notes |
|-----------------|----------|-------|
| Speaker detection (2fps sampling) | ~45 sec | OpenCV on CPU |
| Clip generation × 7 (FFmpeg) | ~3-5 min | depends on hardware |
| Subtitle burning × 7 | ~2-3 min | per clip |
| Thumbnail extraction | ~20 sec | |
| **Total CPU time** | **~6-9 min** | on 4-core CPU |

| VM Type | Hourly Rate | Cost per Video |
|---------|-------------|----------------|
| 2 vCPU / 4 GB (DigitalOcean) | $0.018/hr | ~$0.002 |
| 4 vCPU / 8 GB | $0.036/hr | ~$0.004 |
| GPU instance (T4) | $0.35/hr | ~$0.04 (much faster) |

### Storage costs

| Item | Size | Monthly @ $0.023/GB |
|------|------|---------------------|
| Input video (10 min) | ~500 MB | $0.012 |
| 7 output clips (1080p) | ~700 MB | $0.016 |
| Subtitles / thumbnails | ~50 MB | $0.001 |
| **Total storage / video** | ~1.25 GB | **~$0.03/mo** |

---

## Volume Pricing

| Videos/Month | API Cost | Compute | Total / Month | Cost / Video |
|-------------|----------|---------|---------------|--------------|
| 10 | $1.20 | $0.50 | $1.70 | **$0.17** |
| 50 | $6.00 | $2.00 | $8.00 | **$0.16** |
| 200 | $24.00 | $7.00 | $31.00 | **$0.155** |
| 500 | $60.00 | $15.00 | $75.00 | **$0.15** |
| 1,000 | $120.00 | $25.00 | $145.00 | **$0.145** |

---

## Cost Optimisation Options

### 1. Use local Whisper (eliminate $0.06/video)

```bash
pip install openai-whisper
# Set OPENAI_API_KEY= (empty) in .env to trigger local fallback
# Model sizes: tiny (fastest), base, small, medium, large (most accurate)
```

| Model | Accuracy | Speed (10 min video) | VRAM |
|-------|----------|---------------------|------|
| tiny | ~85% WER | ~30 sec CPU | <1 GB |
| base | ~90% | ~60 sec CPU | 1 GB |
| small | ~93% | ~2 min CPU | 2 GB |
| medium | ~95% | ~5 min CPU | 5 GB |

Savings: **$0.06/video** → break-even at ~100 videos vs. a $6/mo server upgrade.

### 2. Reduce segment count

Edit `node_06` in the workflow: increase the `step` variable to create fewer overlapping segments. Reducing from 50 → 20 segments cuts Claude costs by 60%.

### 3. Use Claude Haiku exclusively

Haiku 4.5 costs ~8× less than Sonnet 4.6. For viral scoring, Haiku performs well since the scoring task is structured and straightforward.

### 4. Cache transcripts

Store `transcript.json` alongside the source video. Re-runs on the same video skip the Whisper API call entirely.

### 5. Batch processing with Anthropic Batch API

For 50+ videos, use the Anthropic Message Batches API for a 50% cost discount:
```python
# In viral_scoring.py, replace single calls with batch requests
client.beta.messages.batches.create(requests=[...])
```

---

## Break-Even Analysis

| Content creator tier | Videos/month | Monthly cost | Cost per clip |
|---------------------|-------------|--------------|---------------|
| Beginner (manual editing) | 4 | $0.68 | $0.024 |
| Part-time creator | 20 | $3.20 | $0.023 |
| Full-time creator | 80 | $12.40 | $0.022 |
| Agency / studio | 400 | $60.00 | $0.021 |

> A freelance video editor charges $15-50 per short-form clip.
> This system pays for itself on the **first clip** of the first video.
