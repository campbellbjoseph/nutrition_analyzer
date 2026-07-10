#!/usr/bin/env python3
"""
Phase 4 -- CLI wrapper.

    python3 analyze.py my_export.csv --age 34 --sex male

Thin script: parses arguments, calls into parser.py / analyzer.py /
food_recommender.py, and prints the results. All the real logic lives in
those three library modules -- Phase 5's web layer will call the exact same
functions and swap print() for a JSON response.
"""
from __future__ import annotations

import argparse
import sys
 
from parser import parse_cronometer_csv
from analyzer import UserProfile, analyze_deficiencies, NutrientStatus
from food_recommender import FDCClient, build_food_pool, recommend_foods, CANDIDATE_FOODS
from local_food_data import LocalFDCClient


def _parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Analyze a Cronometer Daily Nutrition export for nutrient "
            "deficiencies and recommend whole foods to close the gaps."
        )
    )
    p.add_argument("csv_path", help="Path to a Cronometer 'Daily Nutrition' CSV export")
    p.add_argument("--age", type=int, required=True, help="Your age in years (19+)")
    p.add_argument("--sex", choices=["male", "female"], required=True)
    p.add_argument(
        "--no-food-recs", action="store_true",
        help="Skip the USDA food recommendation step (Phase 3) entirely.",
    )
    p.add_argument(
        "--fdc-api-key", default=None,
        help="USDA FDC API key (defaults to the FDC_API_KEY environment variable). "
             "Ignored if --foundation-json/--sr-legacy-json are given.",
    )
    p.add_argument(
        "--foundation-json", default=None,
        help="Path to a downloaded FDC 'Foundation Foods' JSON file. If given (with or "
             "without --sr-legacy-json), food lookups use this local file instead of "
             "the live FDC API -- no API key or network access needed.",
    )
    p.add_argument(
        "--sr-legacy-json", default=None,
        help="Path to a downloaded FDC 'SR Legacy' JSON file, for broader food coverage "
             "than Foundation Foods alone. Can be used with or without --foundation-json.",
    )
    p.add_argument(
        "--use-full-database", action="store_true",
        help="Consider every food in the local JSON file(s) as a recommendation candidate, "
             "instead of the curated CANDIDATE_FOODS list. Requires --foundation-json and/or "
             "--sr-legacy-json. Slower to score (thousands of foods instead of ~50) but much "
             "broader coverage.",
    )
    p.add_argument(
        "--exclude-categories", default="Beverages",
        help="Comma-separated FDC food category names to exclude from local JSON data "
             "(case-insensitive), e.g. 'Beverages,Fast Foods'. Default: Beverages. Pass an "
             "empty string to disable category filtering entirely. Only applies to "
             "--foundation-json/--sr-legacy-json; the live API path is unaffected.",
    )
    p.add_argument("--top-n", type=int, default=6, help="Number of foods to recommend (default: 6)")
    p.add_argument(
        "--cache-path", default="fdc_cache.json",
        help="Where to cache FDC food lookups between runs (default: fdc_cache.json)",
    )
    p.add_argument(
        "--show-adequate", action="store_true",
        help="Also list nutrients that are already adequate",
    )
    return p.parse_args(argv)


def _status_line(s: NutrientStatus) -> str:
    if s.status == "no_data":
        return f"  {s.nutrient:14s}  -- not present in this export"
    pct = f"{s.pct_of_target:5.1f}%" if s.pct_of_target is not None else "  n/a"
    target = f"{s.target:8.2f}" if s.target is not None else "    n/a"
    return (
        f"  {s.nutrient:14s}  {s.median_intake:8.2f} {s.unit:4s}  "
        f"vs {s.target_type or '?':3s} {target}  -> {pct}  [{s.status}]"
    )


def print_deficiency_report(report) -> None:
    print(f"Window analyzed: {report.window[0]} to {report.window[1]} ({report.days_analyzed} days logged)")
    print(f"Profile: age {report.profile.age}, {report.profile.sex}")
    print()

    deficiencies = report.deficiencies()
    print(f"=== DEFICIENT / BORDERLINE ({len(deficiencies)}) ===")
    if not deficiencies:
        print("  None -- nice work.")
    for s in deficiencies:
        print(_status_line(s))

    excesses = report.excesses()
    if excesses:
        print()
        print(f"=== ABOVE RECOMMENDED CEILING ({len(excesses)}) ===")
        for s in excesses:
            ul_label = s.ul_type or "UL"
            print(f"  {s.nutrient:14s}  {s.median_intake:8.2f} {s.unit:4s}  vs {ul_label} {s.ul:8.2f}")

    no_data = report.no_data()
    if no_data:
        print()
        print(f"=== NOT TRACKED IN THIS EXPORT ({len(no_data)}) ===")
        for s in no_data:
            print(f"  {s.nutrient}")

    if report.limitations:
        print()
        print("=== KNOWN LIMITATIONS ===")
        for note in report.limitations:
            print(f"  - {note}")


def print_food_recommendations(recs) -> None:
    print()
    print("=== RECOMMENDED FOODS (per 100g serving) ===")
    if not recs:
        print("  No recommendations -- either no deficiencies found, or no food data available.")
        return
    for i, r in enumerate(recs, 1):
        addressed = ", ".join(f"{n} {pct:.0f}%" for n, pct in r.addressed)
        print(f"  {i}. {r.food.description}  ({r.food.data_type})")
        print(f"     closes: {addressed}")


def main(argv=None) -> int:
    args = _parse_args(argv)

    try:
        parsed = parse_cronometer_csv(args.csv_path)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error reading {args.csv_path}: {e}", file=sys.stderr)
        return 1

    print(f"Parsed {args.csv_path}")
    print(f"Date range: {parsed.date_range[0]} to {parsed.date_range[1]}")
    print(f"Days in range: {parsed.days_in_range}, days with logged data: {parsed.days_logged}")
    if parsed.skipped_dates:
        print(f"Skipped (no data logged): {parsed.skipped_dates}")
    print()

    if parsed.days_logged == 0:
        print("No logged days in this export -- nothing to analyze.", file=sys.stderr)
        return 1

    try:
        profile = UserProfile(age=args.age, sex=args.sex)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    report = analyze_deficiencies(parsed.daily, profile)
    print_deficiency_report(report)

    if args.show_adequate:
        adequate = [s for s in report.statuses if s.status == "adequate"]
        print()
        print(f"=== ADEQUATE ({len(adequate)}) ===")
        for s in adequate:
            print(_status_line(s))

    if args.no_food_recs:
        return 0

    if not report.deficiencies():
        print()
        print("No deficiencies found -- skipping food recommendations.")
        return 0

    using_local_data = args.foundation_json or args.sr_legacy_json

    if args.use_full_database and not using_local_data:
        print(
            "Error: --use-full-database requires --foundation-json and/or --sr-legacy-json "
            "(there's no full-database mode for the live API -- that would mean fetching the "
            "whole database one food at a time over the network).",
            file=sys.stderr,
        )
        return 1

    try:
        if using_local_data:
            json_paths = [p for p in (args.foundation_json, args.sr_legacy_json) if p]
            excluded_categories = {c.strip() for c in args.exclude_categories.split(",") if c.strip()}
            client = LocalFDCClient(json_paths, excluded_categories=excluded_categories)
        else:
            client = FDCClient(api_key=args.fdc_api_key)
    except ValueError as e:
        print()
        print(f"Skipping food recommendations: {e}")
        return 0

    try:
        if args.use_full_database:
            pool = client.all_food_profiles()
            print(f"Scoring against the full local database: {len(pool)} foods")
        else:
            # Caching only matters for cutting down live API calls -- local
            # JSON reads are already fast and complete, so skip writing a
            # redundant cache file when running off local data.
            cache_path = None if using_local_data else args.cache_path
            pool = build_food_pool(client, CANDIDATE_FOODS, cache_path=cache_path)
        recs = recommend_foods(report, pool, top_n=args.top_n)
    except Exception as e:  # network/API errors shouldn't nuke the whole report
        print()
        print(f"Skipping food recommendations: FDC lookup failed ({e})", file=sys.stderr)
        return 0
    except Exception as e:  # network/API errors shouldn't nuke the whole report
        print()
        print(f"Skipping food recommendations: FDC lookup failed ({e})", file=sys.stderr)
        return 0

    print_food_recommendations(recs)
    return 0


if __name__ == "__main__":
    sys.exit(main())