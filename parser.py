from __future__ import annotations
import re
from dataclasses import dataclass
import pandas as pd

_HEADER_UNIT_RE = re.compile(r"^(?P<name>.+?)\s*\((?P<unit>[^()]+)\)$")
VITAMIN_MINERAL_ALIASES: dict[str, str] = {
    "B1 (Thiamine)": "vitamin_b1",
    "B2 (Riboflavin)": "vitamin_b2",
    "B3 (Niacin)": "vitamin_b3",
    "B5 (Pantothenic Acid)": "vitamin_b5",
    "B6 (Pyridoxine)": "vitamin_b6",
    "B12 (Cobalamin)": "vitamin_b12",
    "Folate": "folate",
    "Vitamin A": "vitamin_a",
    "Vitamin C": "vitamin_c",
    "Vitamin D": "vitamin_d",
    "Vitamin E": "vitamin_e",
    "Vitamin K": "vitamin_k",
    "Calcium": "calcium",
    "Copper": "copper",
    "Iron": "iron",
    "Magnesium": "magnesium",
    "Manganese": "manganese",
    "Phosphorus": "phosphorus",
    "Potassium": "potassium",
    "Selenium": "selenium",
    "Sodium": "sodium",
    "Zinc": "zinc",
}

_UNIT_CONVERSIONS: dict[str, tuple[str, float, str]] = {
    "vitamin_d": ("IU", 0.025, "mcg"),
}
_UNIT_DISPLAY_FIXES = {"µg": "mcg"}


@dataclass
class ParsedNutritionData:
    daily: pd.DataFrame 
    date_range: tuple[str, str]
    days_in_range: int
    days_logged: int
    skipped_dates: list[str]


def _parse_header(header: str) -> tuple[str, str] | None:
    match = _HEADER_UNIT_RE.match(header.strip())
    if not match:
        return None
    name = match.group("name").strip()
    unit = _UNIT_DISPLAY_FIXES.get(match.group("unit").strip(), match.group("unit").strip())
    return name, unit


def parse_cronometer_csv(filepath: str) -> ParsedNutritionData:
    raw = pd.read_csv(filepath)

    if "Date" not in raw.columns:
        raise ValueError("Expected a 'Date' column — is this a Cronometer Daily Summary export?")

    raw["Date"] = pd.to_datetime(raw["Date"]).dt.date

    # Build header -> (canonical_key, unit) map, restricted to columns
    # we have an alias for.
    column_info: dict[str, tuple[str, str]] = {}
    for header in raw.columns:
        parsed = _parse_header(header)
        if parsed is None:
            continue
        name, unit = parsed
        if name in VITAMIN_MINERAL_ALIASES:
            column_info[header] = (VITAMIN_MINERAL_ALIASES[name], unit)

    missing_aliases = set(VITAMIN_MINERAL_ALIASES.values()) - {k for k, _ in column_info.values()}
    if missing_aliases:
        print(f"Note: export is missing expected nutrient columns: {sorted(missing_aliases)}")

    if "Energy (kcal)" in raw.columns:
        logged_mask = raw["Energy (kcal)"].notna()
    else:
        nutrient_cols = list(column_info.keys())
        logged_mask = raw[nutrient_cols].notna().any(axis=1)

    skipped_dates = [str(d) for d in raw.loc[~logged_mask, "Date"]]
    logged = raw.loc[logged_mask].copy()

    records = []
    for header, (key, unit) in column_info.items():
        for _, row in logged[["Date", header]].iterrows():
            amount = row[header]
            if pd.isna(amount):
                continue
            records.append({"date": row["Date"], "nutrient": key, "amount": float(amount), "unit": unit})

    tidy = pd.DataFrame(records, columns=["date", "nutrient", "amount", "unit"])

    for key, (expected_unit, factor, target_unit) in _UNIT_CONVERSIONS.items():
        mask = tidy["nutrient"] == key
        if mask.any():
            wrong_unit_rows = mask & (tidy["unit"] != expected_unit)
            if wrong_unit_rows.any():
                print(f"Warning: expected {key} in {expected_unit}, found different unit — skipping conversion")
                continue
            tidy.loc[mask, "amount"] = tidy.loc[mask, "amount"] * factor
            tidy.loc[mask, "unit"] = target_unit

    return ParsedNutritionData(
        daily=tidy,
        date_range=(str(raw["Date"].min()), str(raw["Date"].max())),
        days_in_range=len(raw),
        days_logged=int(logged_mask.sum()),
        skipped_dates=skipped_dates,
    )


if __name__ == "__main__":
    import sys

    result = parse_cronometer_csv(sys.argv[1])
    print(f"Date range: {result.date_range[0]} to {result.date_range[1]}")
    print(f"Days in range: {result.days_in_range}, days with logged data: {result.days_logged}")
    if result.skipped_dates:
        print(f"Skipped (no data logged): {result.skipped_dates}")
    print()
    print(result.daily.pivot(index="date", columns="nutrient", values="amount"))