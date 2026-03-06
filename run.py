import argparse

from config import load_config


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
        print("[DRY RUN] No API calls or sheet writes will be made.")

    print(f"[INFO] Mode       : {args.mode}")
    print(f"[INFO] CSV        : {args.csv or '(none — generation only)'}")
    print(f"[INFO] Dry run    : {args.dry_run}")
    print(f"[INFO] Rate delay : {config.rate_limit_delay}s")


if __name__ == "__main__":
    main()
