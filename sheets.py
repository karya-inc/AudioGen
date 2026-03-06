from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

from config import Config
from ingestion import IngestionRow

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SHEET_NAME = "Audio Tracker"
HEADERS = ["Key", "Language", "Text", "Audio Status", "Drive Link", "Last Updated", "Notes"]

# 1-based column positions matching HEADERS order
_COL_KEY = 1
_COL_LANGUAGE = 2
_COL_TEXT = 3
_COL_STATUS = 4
_COL_DRIVE_LINK = 5
_COL_LAST_UPDATED = 6
_COL_NOTES = 7


@dataclass
class SheetRow:
    row_index: int  # 1-based sheet row (row 1 = header, data starts at 2)
    key: str
    language: str
    text: str
    status: str
    drive_link: str
    last_updated: str
    notes: str


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


class AudioTrackerSheet:
    def __init__(self, config: Config):
        sa_path = Path(config.google_service_account_json)
        if not sa_path.exists():
            raise SystemExit(
                f"[ERROR] Service account file not found: {sa_path}\n"
                f"        Set GOOGLE_SERVICE_ACCOUNT_JSON in .env to a valid path."
            )

        creds = Credentials.from_service_account_file(str(sa_path), scopes=_SCOPES)
        client = gspread.authorize(creds)

        try:
            spreadsheet = client.open_by_key(config.google_sheet_id)
        except gspread.SpreadsheetNotFound:
            raise SystemExit(
                f"[ERROR] Spreadsheet not found: {config.google_sheet_id}\n"
                f"        Ensure the sheet exists and the service account has access."
            )

        self._ws = self._ensure_worksheet(spreadsheet)

    def _ensure_worksheet(self, spreadsheet: gspread.Spreadsheet) -> gspread.Worksheet:
        try:
            ws = spreadsheet.worksheet(SHEET_NAME)
        except gspread.WorksheetNotFound:
            print(f"[INFO] Sheet '{SHEET_NAME}' not found — creating it.")
            ws = spreadsheet.add_worksheet(
                title=SHEET_NAME, rows=1000, cols=len(HEADERS)
            )
            ws.append_row(HEADERS, value_input_option="RAW")
        return ws

    def load_rows(self) -> dict[tuple[str, str], SheetRow]:
        """Load all sheet rows into a dict keyed by (Key, Language)."""
        all_values = self._ws.get_all_values()
        if len(all_values) <= 1:
            return {}

        result: dict[tuple[str, str], SheetRow] = {}
        for i, row in enumerate(all_values[1:], start=2):  # skip header; row 1 = header
            row = row + [""] * (len(HEADERS) - len(row))  # pad short rows
            key = row[_COL_KEY - 1].strip()
            language = row[_COL_LANGUAGE - 1].strip()
            if not key or not language:
                continue
            result[(key, language)] = SheetRow(
                row_index=i,
                key=key,
                language=language,
                text=row[_COL_TEXT - 1].strip(),
                status=row[_COL_STATUS - 1].strip(),
                drive_link=row[_COL_DRIVE_LINK - 1].strip(),
                last_updated=row[_COL_LAST_UPDATED - 1].strip(),
                notes=row[_COL_NOTES - 1].strip(),
            )
        return result

    def upsert_rows(
        self, ingestion_rows: list[IngestionRow], dry_run: bool = False
    ) -> dict[str, int]:
        """Apply Section 5 upsert logic for each ingestion row.

        Returns stats dict with keys: inserted, updated, unchanged.
        """
        existing = self.load_rows()
        now = _now_ts()

        rows_to_append: list[list] = []
        rows_to_update: list[tuple[int, str, str]] = []  # (row_index, new_text, now)

        for ir in ingestion_rows:
            composite = (ir.key, ir.language)

            if composite not in existing:
                # New row — insert with needs_generation
                rows_to_append.append(
                    [ir.key, ir.language, ir.text, "needs_generation", "", now, ""]
                )
            else:
                ex = existing[composite]
                if ex.text != ir.text:
                    # Text changed — reset to needs_generation, clear Drive link
                    rows_to_update.append((ex.row_index, ir.text, now))
                # Text unchanged — no action regardless of current status

        stats = {
            "inserted": len(rows_to_append),
            "updated": len(rows_to_update),
            "unchanged": len(ingestion_rows) - len(rows_to_append) - len(rows_to_update),
        }

        if dry_run:
            for row in rows_to_append:
                print(f"[DRY RUN] Would insert : {row[0]} | {row[1]}")
            for row_index, text, _ in rows_to_update:
                sheet_row = next(r for r in existing.values() if r.row_index == row_index)
                print(
                    f"[DRY RUN] Would update : {sheet_row.key} | {sheet_row.language} "
                    f"(text changed → needs_generation)"
                )
            return stats

        if rows_to_append:
            self._ws.append_rows(rows_to_append, value_input_option="RAW")

        for row_index, new_text, ts in rows_to_update:
            # Update columns C (Text) through G (Notes): text, status, drive_link cleared, timestamp, notes cleared
            self._ws.update(
                values=[[new_text, "needs_generation", "", ts, ""]],
                range_name=f"C{row_index}:G{row_index}",
            )

        return stats

    def get_pending_rows(self) -> list[SheetRow]:
        """Return all rows with status needs_generation."""
        return [r for r in self.load_rows().values() if r.status == "needs_generation"]

    def set_status(self, row: SheetRow, status: str, notes: str = "") -> None:
        """Update status and timestamp for a row, preserving the Drive link."""
        now = _now_ts()
        self._ws.update(
            values=[[status, row.drive_link, now, notes]],
            range_name=f"D{row.row_index}:G{row.row_index}",
        )
        row.status = status
        row.last_updated = now
        row.notes = notes

    def update_result(
        self, row: SheetRow, drive_link: str, status: str, notes: str = ""
    ) -> None:
        """Write the final Drive link, status, and timestamp for a row."""
        now = _now_ts()
        self._ws.update(
            values=[[status, drive_link, now, notes]],
            range_name=f"D{row.row_index}:G{row.row_index}",
        )
        row.status = status
        row.drive_link = drive_link
        row.last_updated = now
        row.notes = notes
