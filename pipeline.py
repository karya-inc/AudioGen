import sys
from pathlib import Path
from typing import Callable

from config import iso_filename
from drive import DriveUploader
from generator import OnSuccess
from sheets import AudioTrackerSheet, SheetRow


def _write_with_retry(fn: Callable[[], None], row: SheetRow) -> bool:
    """Call fn(); if it raises, log and retry once. Returns True on success."""
    for attempt in range(2):
        try:
            fn()
            return True
        except Exception as e:
            if attempt == 0:
                print(
                    f"[WARN] Sheet write failed for {row.key} | {row.language}: {e} "
                    f"— retrying once..."
                )
            else:
                print(
                    f"[ERROR] Sheet write failed again for {row.key} | {row.language}: {e} "
                    f"— audio is NOT re-generated; retry the sheet update manually."
                )
    return False


def make_on_success(
    sheet: AudioTrackerSheet,
    uploader: DriveUploader,
    dry_run: bool = False,
) -> OnSuccess:
    """Return the OnSuccess callback that uploads to Drive and updates the sheet.

    Failure behaviour per PRD Section 9:
    - Drive upload failure  → mark row 'error', retain local mp3, continue
    - Sheet write failure   → log, retry once; do not re-generate audio
    """

    def on_success(row: SheetRow, path: Path) -> None:
        if dry_run:
            print(f"[DRY RUN] Would upload {path.name} to Drive and mark generated")
            return

        # 1. Upload to Google Drive
        try:
            drive_link = uploader.upload(path, row.language)
        except Exception as e:
            note = f"Drive upload failed: {e}"
            print(f"[ERROR] {row.key} | {row.language}: {note}")
            print(f"        Local file retained at: {path}")
            _write_with_retry(
                lambda: sheet.set_status(row, "error", notes=note), row
            )
            return

        # 2. Write Drive link + mark generated
        ok = _write_with_retry(
            lambda: sheet.update_result(row, drive_link, "generated"), row
        )
        if ok:
            print(f"[OK]   Uploaded → {drive_link}")

    return on_success


def retry_errors(
    sheet: AudioTrackerSheet,
    uploader: DriveUploader,
    dry_run: bool = False,
) -> tuple[int, int]:
    """For every 'error' row:
    - If output/{key}__{language}.mp3 exists → re-upload to Drive (skip ElevenLabs)
    - Otherwise → reset to needs_generation for the next normal run

    Returns (uploaded, reset).
    """
    error_rows = [r for r in sheet.load_rows().values() if r.status == "error"]
    if not error_rows:
        print("[INFO] No rows with error status. Nothing to retry.")
        return 0, 0

    print(f"[INFO] Found {len(error_rows)} error row(s) to retry.\n")
    uploaded, reset = 0, 0

    for row in error_rows:
        path = Path("output") / row.language / iso_filename(row.language, row.key)

        if path.exists():
            print(f"[INFO] Re-uploading: {row.key} | {row.language} ...", end=" ", flush=True)
            if dry_run:
                print(f"\n[DRY RUN] Would re-upload {path.name} and mark generated")
                continue
            try:
                drive_link = uploader.upload(path, row.language)
            except Exception as e:
                note = f"Drive upload failed: {e}"
                print(f"FAILED\n[ERROR] {note}")
                _write_with_retry(lambda: sheet.set_status(row, "error", notes=note), row)
                continue
            ok = _write_with_retry(
                lambda: sheet.update_result(row, drive_link, "generated"), row
            )
            if ok:
                print(f"done\n[OK]   Uploaded → {drive_link}")
                uploaded += 1
        else:
            print(f"[INFO] No local file for {row.key} | {row.language} — resetting to needs_generation")
            if not dry_run:
                _write_with_retry(
                    lambda: sheet.set_status(row, "needs_generation", notes=""), row
                )
                reset += 1

    return uploaded, reset


def print_summary(success: int, errors: int, total: int) -> None:
    skipped = total - success - errors
    parts = [f"{success}/{total} generated successfully"]
    if errors:
        parts.append(f"{errors} error(s)")
    if skipped:
        parts.append(f"{skipped} skipped")
    status = "[DONE]" if not errors else "[DONE WITH ERRORS]"
    print(f"\n{status} {', '.join(parts)}.")


def exit_with_code(errors: int) -> None:
    sys.exit(1 if errors else 0)
