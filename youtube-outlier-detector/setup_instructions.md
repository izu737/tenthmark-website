# YouTube Outlier Detector — Setup Instructions

## What This Workflow Does

Finds videos in your target niches that significantly outperformed their channel's average, fetches their transcripts, and uses Claude AI to generate a topic summary and 3 alternative titles adapted for your channel. Results are written to a Google Sheet.

---

## Prerequisites

| Requirement | Notes |
|---|---|
| n8n (self-hosted or cloud) | v1.30+ recommended |
| YouTube Data API v3 key | Free, via Google Cloud Console |
| Claude API key | Via console.anthropic.com |
| Google Sheets API (OAuth2) | Configured as n8n credential |
| Python 3.8+ | On the machine running n8n |
| `youtube-transcript-api` pip package | `pip install youtube-transcript-api` |

---

## Step 1 — YouTube Data API Key

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or select an existing one)
3. Navigate to **APIs & Services → Library**
4. Search for **"YouTube Data API v3"** and click **Enable**
5. Go to **APIs & Services → Credentials → Create Credentials → API Key**
6. Copy the key — this is your `YOUTUBE_API_KEY`
7. (Optional but recommended) Restrict the key to the YouTube Data API v3

**Free quota:** 10,000 units/day. Each search request costs 100 units; each video stats request costs 1 unit. See cost estimate below.

---

## Step 2 — Claude API Key

1. Go to [console.anthropic.com](https://console.anthropic.com/)
2. Navigate to **API Keys → Create Key**
3. Copy the key — this is your `CLAUDE_API_KEY`

---

## Step 3 — Google Sheets Setup

### Create the Sheet

1. Create a new Google Sheet
2. Rename the first tab to **"YouTube Outliers"** (must match exactly)
3. Add these column headers in row 1 in this exact order:

| A | B | C | D | E | F | G | H | I | J | K | L | M | N | O | P | Q | R | S | T | U |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Timestamp | Video Title | Video URL | Thumbnail URL | Channel Name | Channel ID | Published Date | View Count | Like Count | Comment Count | Channel Avg Views | Outlier Score | Base Score | Recency Boost | Content Boost | Days Since Published | Transcript Available | Summary | Alt Title 1 | Alt Title 2 | Alt Title 3 |

4. Copy the Sheet ID from the URL:
   `https://docs.google.com/spreadsheets/d/**SHEET_ID_IS_HERE**/edit`

### Connect Google Sheets in n8n

1. In n8n, go to **Settings → Credentials → Add Credential**
2. Search for **"Google Sheets OAuth2 API"**
3. Follow the OAuth flow to connect your Google account
4. Note the credential ID (visible in the URL after saving)
5. In the workflow JSON, replace `REPLACE_WITH_YOUR_CREDENTIAL_ID` with your actual credential ID

---

## Step 4 — Install the Python Transcript Script

1. Copy `fetch_transcript.py` to your n8n server:
   ```bash
   sudo mkdir -p /opt/n8n/scripts
   sudo cp fetch_transcript.py /opt/n8n/scripts/
   sudo chmod +x /opt/n8n/scripts/fetch_transcript.py
   ```

2. Install the Python dependency:
   ```bash
   pip install youtube-transcript-api
   # or if using pip3:
   pip3 install youtube-transcript-api
   ```

3. Test it manually:
   ```bash
   python3 /opt/n8n/scripts/fetch_transcript.py dQw4w9WgXcQ
   # Should print JSON with "success": true and a "transcript" field
   ```

4. If n8n runs as a different user (e.g. `n8n` or `node`), install the package for that user:
   ```bash
   sudo -u n8n pip3 install youtube-transcript-api
   ```

---

## Step 5 — Find Your Channel ID

Your channel ID looks like `UCxxxxxxxxxxxxxxxxxxxxxxxxx`.

- Go to your YouTube channel page
- Click **Customize channel**
- The URL will contain `/channel/UCxxx...` — that's your channel ID
- Or use this tool: https://www.tunepocket.com/youtube-channel-id-finder/

---

## Step 6 — Import and Configure the Workflow

1. In n8n, click **Workflows → Import from File**
2. Select `n8n_workflow.json`
3. Open the **"Set Variables"** node and fill in:

| Variable | Value |
|---|---|
| `YOUTUBE_API_KEY` | From Step 1 |
| `CLAUDE_API_KEY` | From Step 2 |
| `MY_CHANNEL_ID` | From Step 5 |
| `TARGET_NICHES` | Comma-separated, e.g. `personal finance,investing,side hustle` |
| `GOOGLE_SHEET_ID` | From Step 3 |
| `OUTLIER_THRESHOLD` | Minimum outlier score (default: `2.0`) |
| `TRANSCRIPT_SCRIPT_PATH` | Path to script (default: `/opt/n8n/scripts/fetch_transcript.py`) |

4. Open the **"Append to Google Sheets"** node and update the credential reference to your Google Sheets credential

5. Click **Save**

---

## Step 7 — Run the Workflow

1. Click **Test workflow** (or **Execute Workflow** for a production run)
2. Monitor execution in the n8n canvas — each node will show green when successful
3. Check your Google Sheet for results after the run completes

**Tip:** Start with 1–2 niches and a threshold of `3.0` on your first run to validate everything is working before doing a full run.

---

## Outlier Scoring Formula

```
outlierScore = (videoViews / channelAvgViews) × recencyBoost × contentBoost
```

| Factor | Rule | Boost |
|---|---|---|
| Recency boost | Published within 30 days | ×1.3 |
| Recency boost | Published within 60 days | ×1.2 |
| Recency boost | Published within 90 days | ×1.1 |
| Content boost | Title contains money keywords | +0.30 |
| Content boost | Title contains time/urgency keywords | +0.20 |
| Content boost | Title contains curiosity keywords | +0.15 |

A score of `2.0` means the video got at least 2× the channel's average views (before boosts).

---

## Cost Estimate Per Run

### Assumptions
- 3 niches × 10 channels each = 30 channels
- 50 videos fetched per channel = 1,500 videos total
- Top 100 outliers processed with Claude

### YouTube Data API (units used per run)

| Request | Unit cost | Count | Total units |
|---|---|---|---|
| Search channels (per niche) | 100 | 3 | 300 |
| Get channel videos (per channel) | 100 | 30 | 3,000 |
| Get video statistics (per channel) | 1 | 30 | 30 |
| **Total** | | | **3,330 units** |

Free daily quota: 10,000 units → **this run uses ~33% of free daily quota**.
If you exceed the free tier, additional units cost ~$0.068 per 1,000 units. A typical run costs **< $0.25** on the paid tier.

### Claude API (claude-opus-4-7)

| Item | Value |
|---|---|
| Avg tokens per request (input) | ~1,500 (prompt + transcript) |
| Avg tokens per request (output) | ~300 (summary + 3 titles) |
| Requests per run | 100 |
| Total input tokens | ~150,000 |
| Total output tokens | ~30,000 |
| Input cost (at $15/M tokens) | ~$2.25 |
| Output cost (at $75/M tokens) | ~$2.25 |
| **Estimated Claude cost per run** | **~$4.50** |

> To reduce cost, change the model in `Prepare Claude Request` to `claude-haiku-4-5-20251001` (~10× cheaper) at the expense of slightly lower quality titles.

### Google Sheets API
Free — no cost.

### Total estimated cost per run: **~$4.50–$5.00**

---

## Troubleshooting

| Problem | Fix |
|---|---|
| "Transcripts disabled" for many videos | Normal — the workflow handles this gracefully and Claude will analyse based on title alone |
| YouTube quota exceeded | Reduce niches or run on different days |
| Google Sheets authentication error | Re-authenticate the credential in n8n settings |
| Python script not found | Check `TRANSCRIPT_SCRIPT_PATH` in Set Variables |
| Claude returns empty titles | Check `CLAUDE_API_KEY` is valid and has balance |
| Workflow finds 0 channels | Make sure `TARGET_NICHES` uses common search terms |

---

## Scheduling (Optional)

To run automatically every week:
1. Replace the **Manual Trigger** node with a **Schedule Trigger** node
2. Set interval to **Every week** on your preferred day/time
3. Activate the workflow with the toggle in the top-right corner

---

## Google Sheet Column Reference

| Column | Description |
|---|---|
| Timestamp | When the row was written |
| Video Title | Original video title |
| Video URL | Full YouTube URL |
| Thumbnail URL | High-res thumbnail (use `=IMAGE(D2)` in Sheets to display it) |
| Channel Name | Competitor channel name |
| Channel ID | YouTube channel ID |
| Published Date | ISO date the video was published |
| View Count | Total views at time of analysis |
| Like Count | Total likes |
| Comment Count | Total comments |
| Channel Avg Views | Channel's average views across last 50 videos |
| Outlier Score | Final score (higher = bigger outlier) |
| Base Score | Views ÷ channel average (before boosts) |
| Recency Boost | Multiplier applied for recent videos (1.0–1.3) |
| Content Boost | Multiplier applied for keyword matches (1.0–1.65) |
| Days Since Published | Age of video in days |
| Transcript Available | TRUE/FALSE |
| Summary | Claude's 2–3 sentence summary |
| Alt Title 1 | Claude's first alternative title for your channel |
| Alt Title 2 | Claude's second alternative title |
| Alt Title 3 | Claude's third alternative title |

**Pro tip:** Add a formula column `=IMAGE(D2)` next to Thumbnail URL to see thumbnails inline in Sheets.
