import argparse
import sys

from elevenlabs.client import ElevenLabs

from config import load_config
from drive import DriveUploader
from generator import run_batch, run_generate_all, run_one_at_a_time
from ingestion import ingest_csv
from pipeline import exit_with_code, make_on_success, print_summary
from sheets import AudioTrackerSheet

_MODE_RUNNERS = {
    "generate-all": run_generate_all,
    "batch": run_batch,
    "one-at-a-time": run_one_at_a_time,
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Multilingual Audio Generation Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modes:
  generate-all     Process all queued rows automatically (CI-friendly)
  batch            Confirm one key (all languages) at a time
  one-at-a-time    Confirm each language row individually

Examples:
  python run.py --csv strings.csv --mode generate-all
  python run.py --csv strings.csv --mode batch --dry-run
  python run.py --mode generate-all
        """,
    )
    parser.add_argument(
        "--csv",
        metavar="PATH",
        help="Path to input CSV. If omitted, skips ingestion and proceeds to generation only.",
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=["generate-all", "batch", "one-at-a-time"],
        help="Execution mode",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log planned actions without making API calls or sheet writes.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    config = load_config()

    if args.dry_run:
        print("[DRY RUN] No API calls or sheet writes will be made.\n")

    # ── Sheet (always needed to read current state) ───────────────────────────
    sheet = AudioTrackerSheet(config)

    # ── CSV ingestion (optional) ──────────────────────────────────────────────
    if args.csv:
        rows = ingest_csv(args.csv)
        print(f"[INFO] CSV loaded: {len(rows)} (key, language, text) tuple(s)")
        stats = sheet.upsert_rows(rows, dry_run=args.dry_run)
        print(
            f"[INFO] Sheet sync: {stats['inserted']} inserted, "
            f"{stats['updated']} updated, {stats['unchanged']} unchanged"
        )

    # ── Pending rows ──────────────────────────────────────────────────────────
    pending = sheet.get_pending_rows()
    total = len(pending)

    if not pending:
        print("[INFO] No rows with needs_generation status. Nothing to do.")
        sys.exit(0)

    print(f"[INFO] Mode: {args.mode} | {total} row(s) pending\n")

    # ── External clients (skipped in dry-run; credentials not required) ───────
    uploader = None if args.dry_run else DriveUploader(config)
    client = None if args.dry_run else ElevenLabs(api_key=config.elevenlabs_api_key)

    # ── Run ───────────────────────────────────────────────────────────────────
    on_success = make_on_success(sheet, uploader, dry_run=args.dry_run)
    runner = _MODE_RUNNERS[args.mode]
    success, errors = runner(
        pending=pending,
        config=config,
        sheet=sheet,
        client=client,
        on_success=on_success,
        dry_run=args.dry_run,
    )

    # ── Summary ───────────────────────────────────────────────────────────────
    if args.dry_run:
        print(f"\n[DRY RUN] Would process {total} row(s). No changes made.")
        sys.exit(0)

    print_summary(success, errors, total)
    exit_with_code(errors)


if __name__ == "__main__":
    main()
