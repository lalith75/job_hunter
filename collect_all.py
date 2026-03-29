#!/usr/bin/env python3
"""Run all job collectors in sequence: JobSpy (Indeed + LinkedIn + Google Jobs) then Dice.

Usage:
    python collect_all.py                     # all roles, all sources
    python collect_all.py --role "data analyst"  # single role
    python collect_all.py --dry-run           # preview without saving
    python collect_all.py --no-google         # skip Google Jobs
    python collect_all.py --no-dice           # skip Dice
"""

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="Collect jobs from all sources")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing files")
    parser.add_argument("--role", type=str, help="Search a single role instead of all target roles")
    parser.add_argument("--hours", type=int, help="Override hours_old filter")
    parser.add_argument("--results", type=int, help="Override results per role")
    parser.add_argument("--no-google", action="store_true", help="Skip Google Jobs scraping")
    parser.add_argument("--no-dice", action="store_true", help="Skip Dice collection")
    args = parser.parse_args()

    # --- Phase 1: JobSpy (Indeed + LinkedIn + Google Jobs) ---
    print("=" * 60)
    print("PHASE 1: JobSpy (Indeed + LinkedIn + Google Jobs)")
    print("=" * 60)

    from jobspy_collector import load_config, run_collector, HAS_JOBSPY, CONFIG_PATH

    if not HAS_JOBSPY:
        print("ERROR: python-jobspy not installed. Run: pip install python-jobspy")
        return 1
    if not CONFIG_PATH.exists():
        print(f"ERROR: Config not found at {CONFIG_PATH}")
        return 1

    config = load_config()
    run_collector(
        config,
        dry_run=args.dry_run,
        role_filter=args.role,
        hours_override=args.hours,
        results_override=args.results,
        skip_google=args.no_google,
    )

    # --- Phase 2: Dice ---
    if not args.no_dice:
        print()
        print("=" * 60)
        print("PHASE 2: Dice")
        print("=" * 60)

        from dice_collector import run_dice_collector
        import json

        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            dice_config = json.load(f)
        run_dice_collector(dice_config, dry_run=args.dry_run, role_filter=args.role)
    else:
        print("\nSkipping Dice (--no-dice)")

    print()
    print("=" * 60)
    print("DONE — All collectors finished.")
    print("Next step: Open Claude Code and say 'score my jobs'")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
