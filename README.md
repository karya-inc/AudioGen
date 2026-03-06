# AudioGen — Multilingual Audio Generation Pipeline

Automates text-to-speech audio generation for localized string sets. Reads a CSV of translated strings, syncs them to a Google Sheet for tracking, generates `.mp3` files via ElevenLabs, uploads them to Google Drive, and writes the shareable links back to the sheet.

---

## How It Works

```
Input CSV
    │
    ▼
CSV Ingestion       — parse & validate; expand into (key, language, text) tuples
    │
    ▼
Google Sheets Sync  — upsert rows; mark changed/new strings as needs_generation
    │
    ▼
Generation Engine   — call ElevenLabs TTS per row; save to output/
    │
    ▼
Google Drive Upload — upload to AudioAssets/{key}/; set public link
    │
    ▼
Sheet Update        — write Drive link; mark row as generated
```

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Google Cloud — service account

1. Create a project in [Google Cloud Console](https://console.cloud.google.com)
2. Enable **Google Sheets API** and **Google Drive API**
3. Create a **Service Account** (IAM & Admin → Service Accounts)
4. Download the JSON key → save to `credentials/service_account.json`

### 3. Google Sheet

1. Create a new Google Sheet at [sheets.google.com](https://sheets.google.com)
2. Share it with the service account email → **Editor**
3. Copy the Sheet ID from the URL:
   `https://docs.google.com/spreadsheets/d/**SHEET_ID**/edit`

The script auto-creates the `Audio Tracker` tab with correct headers on first run.

### 4. Google Drive — Shared Drive

> **Important:** Service accounts have no personal Drive quota. Files must be stored in a **Shared Drive**.

1. In Google Drive, click **+ New → Shared drive**
2. Add the service account email as a **Contributor** (or higher)
3. Copy the Shared Drive folder ID from its URL:
   `https://drive.google.com/drive/folders/**FOLDER_ID**`

### 5. ElevenLabs

1. Get your API key from [elevenlabs.io](https://elevenlabs.io) → Profile → API Keys
2. Browse the [Voice Library](https://elevenlabs.io/voice-library) → filter by language → **Add to My Voices**
3. Copy voice IDs from **My Voices** or via API:
   ```bash
   curl -H "xi-api-key: YOUR_KEY" https://api.elevenlabs.io/v1/voices
   ```

### 6. Configure `.env`

Copy `.env.example` to `.env` and fill in:

```env
ELEVENLABS_API_KEY=sk-...
GOOGLE_SERVICE_ACCOUNT_JSON=./credentials/service_account.json
GOOGLE_SHEET_ID=your_sheet_id
GOOGLE_DRIVE_FOLDER_ID=your_shared_drive_folder_id
RATE_LIMIT_DELAY=1.0
```

### 7. Configure `voices.yaml`

Replace `<VOICE_ID>` placeholders with real ElevenLabs voice IDs:

```yaml
voices:
  English: "21m00Tcm4TlvDq8ikWAM"
  Hindi: "pNInz6obpgDQGcFmaJgB"
  Kannada: "..."
  # ... one per language
default_voice: "21m00Tcm4TlvDq8ikWAM"  # fallback for unconfigured languages
```

> **Tip:** The model used is `eleven_multilingual_v2`, which supports all 12 languages. You can use a single multilingual voice for everything and refine per-language later.

---

## Input Format

A CSV file with one row per string key and one column per language.

| Column | Required | Description |
|---|---|---|
| `S. No` | No | Row index — ignored |
| `key` | Yes | Unique string identifier (e.g. `selected_language_is`) |
| `English` | No | English text |
| `Hindi` | No | Hindi text |
| *(any language)* | No | Additional language columns are auto-detected |

**Rules:**
- `key` must be unique across all rows
- Empty language cells are silently skipped
- Adding a new language column automatically includes it in generation
- The file must be UTF-8 encoded (UTF-8 BOM is handled automatically)

**Example (`sample.csv`):**

```
S. No,key,English,Hindi,Kannada
0,selected_language_is,Selected language is English,चुनी गई भाषा हिंदी है,ಆಯ್ಕೆ ಮಾಡಲಾದ ಭಾಷೆ ಕನ್ನಡ
1,welcome_message,Welcome,आपका स्वागत है,ಸ್ವಾಗತ
```

---

## Usage

```bash
python run.py --csv <path> --mode <mode> [--dry-run] [--retry-errors]
```

### Arguments

| Argument | Required | Description |
|---|---|---|
| `--csv PATH` | No | Path to input CSV. If omitted, skips ingestion and processes whatever is already queued in the sheet |
| `--mode` | Yes | Execution mode (see below) |
| `--dry-run` | No | Show planned actions without making any API calls or sheet writes |
| `--retry-errors` | No | Retry all rows marked `error` in the sheet (see Retry section) |

### Modes

**`generate-all`** — process everything automatically, no prompts (best for CI/batch runs)
```bash
python run.py --csv strings.csv --mode generate-all
```

**`batch`** — review all languages for one key at a time, confirm before generating
```bash
python run.py --csv strings.csv --mode batch
```
```
─────────────────────────────────────────
Batch 1/6 | Key: selected_language_is
─────────────────────────────────────────
   1. English      → "Selected language is English"
   2. Hindi        → "चुनी गई भाषा हिंदी है"
   3. Kannada      → "ಆಯ್ಕೆ ಮಾಡಲಾದ ಭಾಷೆ ಕನ್ನಡ"

Generate this batch? [y/s/q]:
```

**`one-at-a-time`** — review and confirm each language row individually
```bash
python run.py --csv strings.csv --mode one-at-a-time
```
```
─────────────────────────────────────────
Item 3/24 | selected_language_is | Kannada
─────────────────────────────────────────
Text: "ಆಯ್ಕೆ ಮಾಡಲಾದ ಭಾಷೆ ಕನ್ನಡ"

Generate? [y/s/q]:
```

In both interactive modes: `y` = generate, `s` = skip (stays `needs_generation`), `q` = quit.

### Dry run

Preview what would happen without touching anything:
```bash
python run.py --csv strings.csv --mode generate-all --dry-run
```

---

## Output

### Local files

Generated audio is saved to:
```
output/
└── {key}__{language}.mp3
```
Example: `output/selected_language_is__Hindi.mp3`

Files are **retained after upload** for manual recovery if needed.

### Google Drive

Files are uploaded to:
```
<GOOGLE_DRIVE_FOLDER_ID>/
└── AudioAssets/
    └── {key}/
        ├── selected_language_is__English.mp3
        ├── selected_language_is__Hindi.mp3
        └── ...
```

Subfolders are auto-created. Re-generating a string replaces the existing file and preserves the Drive link.

### Google Sheet (`Audio Tracker` tab)

| Column | Description |
|---|---|
| `Key` | String key |
| `Language` | Language name |
| `Text` | Source text |
| `Audio Status` | `needs_generation` / `generating` / `generated` / `error` / `skipped` |
| `Drive Link` | Shareable link to the `.mp3` on Google Drive |
| `Last Updated` | Timestamp of last write |
| `Notes` | Error messages (if any) |

---

## Retrying errors

If rows show `error` status in the sheet (e.g. after a Drive upload failure), run:

```bash
python run.py --retry-errors --mode generate-all
```

- If `output/{key}__{language}.mp3` exists locally → re-uploads to Drive, marks `generated` (no ElevenLabs call)
- If no local file exists → resets to `needs_generation` to be re-generated on the next normal run

---

## Idempotency & Resumability

- Running with the same CSV multiple times is safe — `generated` rows are never re-processed
- If a run is interrupted mid-way, completed rows keep their `generated` status; the next run picks up from `needs_generation` rows only
- Rows stuck in `generating` (process killed mid-call) can be manually reset to `needs_generation` in the sheet

---

## Project Structure

```
AudioGen/
├── run.py              # CLI entry point
├── config.py           # .env + voices.yaml loader
├── ingestion.py        # CSV parser and validator
├── sheets.py           # Google Sheets read/write layer
├── generator.py        # ElevenLabs TTS + run mode logic
├── drive.py            # Google Drive upload layer
├── pipeline.py         # on_success callback, retry, summary
├── voices.yaml         # Language → ElevenLabs voice ID mapping
├── requirements.txt    # Python dependencies
├── .env.example        # Environment variable template
└── credentials/        # Service account JSON (gitignored)
```
