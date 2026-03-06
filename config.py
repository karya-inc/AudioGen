import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

# ISO 639-1 codes for supported languages
LANGUAGE_ISO: dict[str, str] = {
    "English": "en",
    "Hindi": "hi",
    "Kannada": "kn",
    "Malayalam": "ml",
    "Tamil": "ta",
    "Gujarati": "gu",
    "Odia": "or",
    "Bengali": "bn",
    "Marathi": "mr",
    "Telugu": "te",
    "Punjabi": "pa",
    "Assamese": "as",
    "Bhojpuri": "bho",
}


def iso_filename(language: str, key: str) -> str:
    """Return the canonical audio filename: {iso_code}_{key}.mp3.

    Falls back to the first two lowercase chars of the language name
    for any language not in LANGUAGE_ISO.
    """
    iso = LANGUAGE_ISO.get(language, language.lower()[:2])
    return f"{iso}_{key}.mp3"


@dataclass
class Config:
    elevenlabs_api_key: str
    google_service_account_json: str
    google_sheet_id: str
    google_drive_folder_id: str
    voices: dict
    default_voice: str
    rate_limit_delay: float


def load_config(voices_path: str = "voices.yaml") -> Config:
    missing = []

    elevenlabs_api_key = os.getenv("ELEVENLABS_API_KEY", "")
    if not elevenlabs_api_key:
        missing.append("ELEVENLABS_API_KEY")

    google_service_account_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if not google_service_account_json:
        missing.append("GOOGLE_SERVICE_ACCOUNT_JSON")

    google_sheet_id = os.getenv("GOOGLE_SHEET_ID", "")
    if not google_sheet_id:
        missing.append("GOOGLE_SHEET_ID")

    google_drive_folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "")
    if not google_drive_folder_id:
        missing.append("GOOGLE_DRIVE_FOLDER_ID")

    if missing:
        raise SystemExit(
            f"[ERROR] Missing required environment variables: {', '.join(missing)}\n"
            f"        Copy .env.example to .env and fill in the values."
        )

    rate_limit_delay = float(os.getenv("RATE_LIMIT_DELAY", "1.0"))

    voices_file = Path(voices_path)
    if not voices_file.exists():
        raise SystemExit(f"[ERROR] voices.yaml not found at: {voices_path}")

    with open(voices_file) as f:
        voices_config = yaml.safe_load(f)

    voices = voices_config.get("voices", {})
    default_voice = voices_config.get("default_voice", "")

    return Config(
        elevenlabs_api_key=elevenlabs_api_key,
        google_service_account_json=google_service_account_json,
        google_sheet_id=google_sheet_id,
        google_drive_folder_id=google_drive_folder_id,
        voices=voices,
        default_voice=default_voice,
        rate_limit_delay=rate_limit_delay,
    )
