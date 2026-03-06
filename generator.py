import time
from collections import defaultdict
from pathlib import Path
from typing import Callable

from elevenlabs.client import ElevenLabs
from elevenlabs.core import ApiError

from config import Config
from sheets import AudioTrackerSheet, SheetRow

_OUTPUT_DIR = Path("output")
_RETRY_DELAYS = [2, 4, 8]  # seconds between retries for 5xx (3 retries = 4 total attempts)

# Callback invoked after each successful audio save; receives (row, local_path).
# Phase 7 wires this to the Drive upload + sheet update.
OnSuccess = Callable[[SheetRow, Path], None]


def _get_voice_id(language: str, config: Config) -> str:
    voice_id = config.voices.get(language, "")
    if voice_id and voice_id != "<VOICE_ID>":
        return voice_id
    if config.default_voice and config.default_voice != "<VOICE_ID>":
        print(f"[WARN] No voice configured for '{language}', using default_voice.")
        return config.default_voice
    raise ValueError(
        f"No valid voice ID configured for '{language}' and no valid default_voice. "
        f"Update voices.yaml before running."
    )


def _call_elevenlabs(client: ElevenLabs, voice_id: str, text: str) -> bytes:
    """Call ElevenLabs TTS with 3x exponential backoff on 5xx. Returns raw audio bytes."""
    last_exc: Exception | None = None
    # First element is None (no sleep before first attempt); rest are retry delays.
    for delay in [None] + _RETRY_DELAYS:
        if delay is not None:
            time.sleep(delay)
        try:
            stream = client.text_to_speech.convert(
                voice_id=voice_id,
                text=text,
                model_id="eleven_multilingual_v2",
                output_format="mp3_44100_128",
            )
            return b"".join(stream)
        except ApiError as e:
            if e.status_code is not None and e.status_code >= 500:
                last_exc = e
                continue  # retry on 5xx
            raise  # re-raise 4xx immediately

    raise last_exc  # all retries exhausted


def generate_audio(
    row: SheetRow,
    config: Config,
    sheet: AudioTrackerSheet,
    client: ElevenLabs,
    dry_run: bool = False,
) -> Path | None:
    """Generate audio for one row. Returns local Path on success, None on failure.

    Side effects:
    - Sets row status to 'generating' before the API call (guards against re-runs).
    - Sets row status to 'error' + writes Notes on failure.
    """
    if dry_run:
        print(f"[DRY RUN] Would generate: {row.key} | {row.language}")
        return None

    try:
        voice_id = _get_voice_id(row.language, config)
    except ValueError as e:
        sheet.set_status(row, "error", notes=str(e))
        print(f"[ERROR] {row.key} | {row.language}: {e}")
        return None

    sheet.set_status(row, "generating")
    print(f"[INFO] Generating: {row.key} | {row.language} ...", end=" ", flush=True)

    try:
        audio_bytes = _call_elevenlabs(client, voice_id, row.text)
    except ApiError as e:
        note = f"ElevenLabs API error {e.status_code}: {e.body}"
        sheet.set_status(row, "error", notes=note)
        print(f"FAILED\n[ERROR] {note}")
        return None
    except Exception as e:
        note = f"Unexpected error: {e}"
        sheet.set_status(row, "error", notes=note)
        print(f"FAILED\n[ERROR] {note}")
        return None

    lang_dir = _OUTPUT_DIR / row.language
    lang_dir.mkdir(parents=True, exist_ok=True)
    path = lang_dir / f"{row.key}.mp3"
    path.write_bytes(audio_bytes)
    print("done")
    return path


def _prompt(prompt_text: str) -> str:
    while True:
        choice = input(prompt_text).strip().lower()
        if choice in ("y", "s", "q"):
            return choice
        print("  Please enter y, s, or q.")


def _sep() -> str:
    return "─" * 41


def run_generate_all(
    pending: list[SheetRow],
    config: Config,
    sheet: AudioTrackerSheet,
    client: ElevenLabs,
    on_success: OnSuccess,
    dry_run: bool = False,
) -> tuple[int, int]:
    """Process all pending rows sequentially without user prompts."""
    total = len(pending)
    print(f"[INFO] Found {total} string(s) with needs_generation status.")

    success, errors = 0, 0
    for row in pending:
        path = generate_audio(row, config, sheet, client, dry_run)
        if path is not None:
            on_success(row, path)
            success += 1
        elif not dry_run:
            errors += 1
        if not dry_run:
            time.sleep(config.rate_limit_delay)

    return success, errors


def run_batch(
    pending: list[SheetRow],
    config: Config,
    sheet: AudioTrackerSheet,
    client: ElevenLabs,
    on_success: OnSuccess,
    dry_run: bool = False,
) -> tuple[int, int]:
    """Group pending rows by key and prompt once per key group."""
    groups: dict[str, list[SheetRow]] = defaultdict(list)
    for row in pending:
        groups[row.key].append(row)

    total_batches = len(groups)
    success, errors = 0, 0

    for batch_num, (key, rows) in enumerate(groups.items(), start=1):
        print(f"\n{_sep()}")
        print(f"Batch {batch_num}/{total_batches} | Key: {key}")
        print(_sep())
        for i, r in enumerate(rows, start=1):
            print(f"  {i:2}. {r.language:<12} → \"{r.text}\"")
        print()

        if dry_run:
            print(f"[DRY RUN] Would generate {len(rows)} item(s) for key '{key}'")
            continue

        choice = _prompt("Generate this batch? [y/s/q]: ")
        if choice == "q":
            print("[INFO] Quitting.")
            break
        if choice == "s":
            print("[INFO] Skipped.")
            continue

        for row in rows:
            path = generate_audio(row, config, sheet, client, dry_run)
            if path is not None:
                on_success(row, path)
                success += 1
            else:
                errors += 1
            time.sleep(config.rate_limit_delay)

    return success, errors


def run_one_at_a_time(
    pending: list[SheetRow],
    config: Config,
    sheet: AudioTrackerSheet,
    client: ElevenLabs,
    on_success: OnSuccess,
    dry_run: bool = False,
) -> tuple[int, int]:
    """Present each pending row individually and prompt before each generation."""
    total = len(pending)
    success, errors = 0, 0

    for item_num, row in enumerate(pending, start=1):
        print(f"\n{_sep()}")
        print(f"Item {item_num}/{total} | {row.key} | {row.language}")
        print(_sep())
        print(f"Text: \"{row.text}\"")
        print()

        if dry_run:
            print(f"[DRY RUN] Would generate: {row.key} | {row.language}")
            continue

        choice = _prompt("Generate? [y/s/q]: ")
        if choice == "q":
            print("[INFO] Quitting.")
            break
        if choice == "s":
            print("[INFO] Skipped.")
            continue

        path = generate_audio(row, config, sheet, client, dry_run)
        if path is not None:
            on_success(row, path)
            success += 1
        else:
            errors += 1
        time.sleep(config.rate_limit_delay)

    return success, errors
