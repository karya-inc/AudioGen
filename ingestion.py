import csv
from dataclasses import dataclass
from pathlib import Path

# Columns that carry metadata, not language text
_NON_LANGUAGE_COLUMNS = {"S. No", "key"}


@dataclass(frozen=True)
class IngestionRow:
    key: str
    language: str
    text: str


def ingest_csv(csv_path: str) -> list[IngestionRow]:
    """Parse a CSV and return one IngestionRow per (key, language, text) tuple.

    Skips empty language cells. Aborts with a printed summary on validation errors.
    """
    path = Path(csv_path)
    if not path.exists():
        raise SystemExit(f"[ERROR] CSV file not found: {csv_path}")

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    # Validate required column
    if "key" not in fieldnames:
        raise SystemExit("[ERROR] CSV is missing required 'key' column.")

    errors = []

    # Validate for duplicate or empty keys (row 1 = header, so data starts at row 2)
    seen_keys: dict[str, int] = {}
    for i, row in enumerate(rows, start=2):
        key = row.get("key", "").strip()
        if not key:
            errors.append(f"  Row {i}: empty 'key' value")
            continue
        if key in seen_keys:
            errors.append(
                f"  Row {i}: duplicate key '{key}' (first seen at row {seen_keys[key]})"
            )
        else:
            seen_keys[key] = i

    if errors:
        print("[ERROR] CSV validation failed:")
        for e in errors:
            print(e)
        raise SystemExit(1)

    # All columns except metadata columns are treated as language columns.
    # This makes the system extensible: adding a new column adds a new language.
    language_columns = [col for col in fieldnames if col not in _NON_LANGUAGE_COLUMNS]

    result: list[IngestionRow] = []
    for row in rows:
        key = row["key"].strip()
        for language in language_columns:
            text = row.get(language, "").strip()
            if text:
                result.append(IngestionRow(key=key, language=language, text=text))

    return result
