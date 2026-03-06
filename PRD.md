# Product Requirements Document
## Multilingual Audio Generation Pipeline
**Version:** 1.0  
**Date:** March 6, 2026  
**Status:** Draft

---

## 1. Overview

### 1.1 Purpose
This tool automates the generation of multilingual text-to-speech audio files from a structured CSV input. It integrates ElevenLabs TTS API for audio generation, Google Drive for file storage, and Google Sheets as the primary tracking and status management layer.

### 1.2 Goals
- Eliminate manual audio generation work for localized string sets
- Maintain a single source of truth (Google Sheet) for all string–audio mappings
- Support flexible execution modes to accommodate batch and one-off generation workflows
- Ensure traceability of every generated audio asset via Drive links in the tracking sheet

### 1.3 Out of Scope
- Audio playback or quality review within the tool
- Automatic voice selection per language (configured externally)
- Translation of strings (input CSV is assumed pre-translated)

---

## 2. System Architecture

```
Input CSV
    │
    ▼
┌─────────────────────────────────────┐
│         Script Entry Point          │
│  - Parse CLI args (mode, csv path)  │
└────────────────┬────────────────────┘
                 │
    ┌────────────▼────────────┐
    │   CSV Ingestion Layer   │
    │  - Parse CSV            │
    │  - Normalize rows       │
    │  - Detect changes       │
    └────────────┬────────────┘
                 │
    ┌────────────▼────────────┐
    │   Google Sheets Layer   │
    │  - Read existing rows   │
    │  - Upsert changed rows  │
    │  - Mark needs_generation│
    └────────────┬────────────┘
                 │
    ┌────────────▼────────────┐
    │   Generation Engine     │
    │  - Filter by status     │
    │  - Apply run mode       │
    │  - Call ElevenLabs API  │
    └────────────┬────────────┘
                 │
    ┌────────────▼────────────┐
    │   Google Drive Layer    │
    │  - Upload audio file    │
    │  - Return shareable URL │
    └────────────┬────────────┘
                 │
    ┌────────────▼────────────┐
    │   Sheet Update Layer    │
    │  - Write Drive link     │
    │  - Update status        │
    └─────────────────────────┘
```

---

## 3. Input Specification

### 3.1 CSV Format
The input CSV contains one row per string key, with columns for each supported language.

| Column | Description |
|---|---|
| `S. No` | Row index (ignored by script) |
| `key` | Unique string identifier (e.g., `selected_language_is`) |
| `English` | English text |
| `Hindi` | Hindi text |
| `Kannada` | Kannada text |
| `Malayalam` | Malayalam text |
| `Tamil` | Tamil text |
| `Gujarati` | Gujarati text |
| `Odia` | Odia text |
| `Bengali` | Bengali text |
| `Marathi` | Marathi text |
| `Telugu` | Telugu text |
| `Punjabi` | Punjabi text |
| `Assamese` | Assamese text |

**Notes:**
- Language columns are extensible; adding a new column adds a new language automatically
- Empty cells in language columns are skipped (no row created in sheet)
- Keys must be unique per CSV; duplicate keys cause a validation error

### 3.2 CLI Arguments

```bash
python run.py [--csv <path>] --mode <generate-all|batch|one-at-a-time>
```

| Argument | Required | Description |
|---|---|---|
| `--csv` | No | Path to input CSV. If omitted, script skips ingestion and proceeds to generation only |
| `--mode` | Yes | Execution mode (see Section 6) |
| `--dry-run` | No | Parses and logs planned actions without making API calls or sheet writes |

---

## 4. Google Sheet Schema

### 4.1 Sheet Name
`Audio Tracker`

The script **auto-creates** this sheet tab with the correct column headers if it does not exist in the configured spreadsheet.

### 4.2 Column Schema

| Column | Type | Description |
|---|---|---|
| `Key` | String | String key from CSV (e.g., `selected_language_is`) |
| `Language` | String | Language name (e.g., `Hindi`) |
| `Text` | String | Localized text to be converted to audio |
| `Audio Status` | Enum | Current status of the audio asset (see 4.3) |
| `Drive Link` | URL | Shareable Google Drive link to the generated `.mp3` file |
| `Last Updated` | Timestamp | Auto-set on every row write |
| `Notes` | String | Optional. Error messages or manual annotations |

### 4.3 Audio Status Values

| Status | Description |
|---|---|
| `needs_generation` | Queued for audio generation |
| `generating` | Currently being processed (guards against re-runs) |
| `generated` | Audio successfully created and uploaded |
| `error` | Generation or upload failed; see `Notes` column |
| `skipped` | Manually marked to exclude from generation |

### 4.4 Row Identity
A row is uniquely identified by the composite key: **`Key` + `Language`**. This pair is used for all upsert operations.

---

## 5. CSV Ingestion Behavior

When `--csv` is provided:

1. Parse the CSV and expand each row into `(key, language, text)` tuples
2. For each tuple, look up the existing row in the sheet by `(Key, Language)`
3. Apply the following logic:

| Condition | Action |
|---|---|
| Row does not exist | Insert new row with status `needs_generation` |
| Row exists, text is unchanged, status is `generated` | No change |
| Row exists, text is unchanged, status is `needs_generation` or `error` | No change (already queued) |
| Row exists, text has changed | Update `Text`, set status to `needs_generation`, clear `Drive Link` |
| Row exists in sheet but not in CSV | No change (sheet row is preserved as-is) |

When `--csv` is **not** provided, the ingestion phase is skipped entirely. The script proceeds directly to the generation phase using whatever rows currently have `needs_generation` status.

---

## 6. Execution Modes

### 6.1 `generate-all`
- Fetches all rows with status `needs_generation`
- Processes all of them sequentially without any user prompts
- Best for automated/CI runs

```
[INFO] Found 24 strings with needs_generation status.
[INFO] Generating: selected_language_is | Hindi ...
[OK]   Uploaded → https://drive.google.com/...
...
[DONE] 24/24 generated successfully.
```

### 6.2 `batch`
- Groups all `needs_generation` rows by `Key`
- Presents one batch (all languages for one key) at a time
- Prompts user for confirmation before generating each batch
- User can confirm (`y`), skip (`s`), or quit (`q`)

```
─────────────────────────────────────────
Batch 1/6 | Key: selected_language_is
─────────────────────────────────────────
  1. English   → "Selected language is English"
  2. Hindi     → "चुनी गई भाषा हिंदी है"
  3. Kannada   → "ಆಯ್ಕೆ ಮಾಡಲಾದ ಭಾಷೆ ಕನ್ನಡ"
  ... (12 languages)

Generate this batch? [y/s/q]:
```

### 6.3 `one-at-a-time`
- Presents each `needs_generation` row individually
- Prompts confirmation before each generation
- User can confirm (`y`), skip (`s`), or quit (`q`)

```
─────────────────────────────────────────
Item 3/24 | selected_language_is | Kannada
─────────────────────────────────────────
Text: "ಆಯ್ಕೆ ಮಾಡಲಾದ ಭಾಷೆ ಕನ್ನಡ"

Generate? [y/s/q]:
```

In all modes, skipped items retain their `needs_generation` status and are picked up on the next run.

---

## 7. Audio Generation (ElevenLabs)

### 7.1 Voice Configuration
Voice IDs are configured in a `voices.yaml` config file, mapping each language to an ElevenLabs voice ID:

```yaml
voices:
  English: "<VOICE_ID>"
  Hindi: "<VOICE_ID>"
  Kannada: "<VOICE_ID>"
  Malayalam: "<VOICE_ID>"
  Tamil: "<VOICE_ID>"
  Gujarati: "<VOICE_ID>"
  Odia: "<VOICE_ID>"
  Bengali: "<VOICE_ID>"
  Marathi: "<VOICE_ID>"
  Telugu: "<VOICE_ID>"
  Punjabi: "<VOICE_ID>"
  Assamese: "<VOICE_ID>"
default_voice: "<VOICE_ID>"  # fallback if language not listed
```

The committed `voices.yaml` uses `<VOICE_ID>` placeholders for all languages. Replace each with the actual ElevenLabs voice ID before running.

### 7.2 API Call

- **Endpoint:** `POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}`
- **Model:** `eleven_multilingual_v2`
- **Output format:** `mp3_44100_128`
- **Timeout:** 30 seconds per request
- **Retry policy:** 3 retries with exponential backoff on 5xx errors

### 7.3 Output File Naming
```
{key}__{language}.mp3
```
Example: `selected_language_is__Hindi.mp3`

---

## 8. Google Drive Storage

### 8.1 Folder Structure
```
Google Drive/
└── AudioAssets/
    └── {key}/
        ├── selected_language_is__English.mp3
        ├── selected_language_is__Hindi.mp3
        └── ...
```

### 8.2 Upload Behavior
- The `AudioAssets/{key}/` subfolder is **auto-created** if it does not exist
- If a file with the same name already exists in the folder, it is **replaced** (new version uploaded, same Drive link preserved where possible)
- All uploaded files are set to **"Anyone with link can view"** sharing permission
- The shareable link is written back to the sheet in the `Drive Link` column
- Generated audio is saved locally to `output/{key}__{language}.mp3` and retained after upload

---

## 9. Error Handling

| Failure Point | Behavior |
|---|---|
| ElevenLabs API error (4xx) | Mark row as `error`, log message in `Notes`, continue to next item |
| ElevenLabs API error (5xx) | Retry 3x, then mark as `error` |
| Google Drive upload failure | Mark row as `error`, audio file retained locally for manual upload |
| Google Sheet write failure | Log to console, retry once; script does not re-generate audio |
| Invalid CSV format | Abort ingestion, print validation errors, exit without modifying sheet |
| Missing voice config for language | Use `default_voice`, log a warning |

On any unrecoverable error, the script exits with a non-zero code and prints a summary of failed items.

---

## 10. Configuration & Secrets

All secrets are stored in a `.env` file (not committed to version control):

```env
ELEVENLABS_API_KEY=sk-...
GOOGLE_SERVICE_ACCOUNT_JSON=./credentials/service_account.json
GOOGLE_SHEET_ID=1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms
GOOGLE_DRIVE_FOLDER_ID=1a2b3c4d...
```

A `voices.yaml` file configures language-to-voice mappings (see Section 7.1).

---

## 11. Tech Stack

| Component | Technology |
|---|---|
| Script language | Python 3.10+ |
| ElevenLabs client | `elevenlabs` PyPI package |
| Dependency management | `pip` + `requirements.txt` |
| Local audio storage | `output/` directory (retained after upload) |
| Google Sheets | `gspread` library with service account auth |
| Google Drive | `google-api-python-client` |
| CLI | `argparse` |
| Config | `python-dotenv` + `PyYAML` |

---

## 12. Non-Functional Requirements

- **Idempotency:** Running the script multiple times with the same CSV must not re-generate already `generated` rows
- **Resumability:** If a run is interrupted, already-generated rows retain their status; the next run picks up where it left off
- **Auditability:** The `Last Updated` timestamp column records every change
- **Concurrency:** Script is single-threaded to avoid ElevenLabs rate limit issues; parallel mode is a future enhancement
- **Rate limiting:** Enforce a configurable delay between ElevenLabs API calls (default: 1 second)

---

## 13. Implementation Phases

Each phase maps to one atomic commit.

| Phase | Commit Message | Scope |
|---|---|---|
| 1 | `feat: project scaffold with CLI entry point and config loading` | `run.py`, `config.py`, `requirements.txt`, `.env.example`, `voices.yaml`, `.gitignore` |
| 2 | `feat: CSV ingestion layer with validation and normalization` | `ingestion.py` — parse, normalize to `(key, language, text)`, validate |
| 3 | `feat: Google Sheets layer with upsert and status management` | `sheets.py` — auth, auto-create tab, read rows, upsert per Section 5 |
| 4 | `feat: ElevenLabs generation engine with all three run modes` | `generator.py` — filter, modes, API call, retry, rate limiting, local save |
| 5 | `feat: Google Drive upload with folder auto-creation and sharing` | `drive.py` — auth, folder creation, upload, replace, share, return URL |
| 6 | `feat: sheet status updates, Drive link writes, and error handling` | Write Drive link, set status, handle errors, exit codes |
| 7 | `feat: wire all layers together with dry-run mode and run summary` | Full pipeline orchestration, `--dry-run`, final summary line |

---

## 14. Future Enhancements

- Web UI dashboard mirroring the Google Sheet status view
- Slack/email notification on batch completion
- Audio preview before confirmation in interactive modes
- Parallel generation with configurable concurrency
- Support for SSML input for fine-grained pronunciation control
- Automatic voice quality scoring and flagging