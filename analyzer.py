"""
Phase 2 — Deficiency analyzer.

Pure library code: no print(), no file I/O, no CLI. Consumes the tidy
long-format DataFrame produced by parser.parse_cronometer_csv() (columns:
date, nutrient, amount, unit) and a UserProfile, and returns a structured
DeficiencyReport. The CLI (Phase 4) and any future web layer (Phase 5) are
both thin wrappers around analyze_deficiencies().
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from reference_data import DRI_TABLE, get_target, get_ul, KNOWN_LIMITATIONS

# Classification thresholds, as a fraction of the RDA/AI target.
DEFICIENT_THRESHOLD = 0.50   # < 50% of target
BORDERLINE_THRESHOLD = 1.00  # 50-99% of target is "borderline"; >=100% is "adequate"


@dataclass
class UserProfile:
    age: int
    sex: str  # "male" or "female" (case-insensitive; "m"/"f" also accepted)

    def __post_init__(self) -> None:
        s = self.sex.strip().lower()
        if s in ("m", "male"):
            self.sex = "male"
        elif s in ("f", "female"):
            self.sex = "female"
        else:
            raise ValueError(f"sex must be 'male' or 'female', got {self.sex!r}")
        if self.age < 19:
            raise ValueError(
                "This tool's reference data only covers adults (age 19+); "
                f"got age={self.age}."
            )


@dataclass
class NutrientStatus:
    nutrient: str
    unit: str
    status: str  # "deficient" | "borderline" | "adequate" | "excess" | "no_data"
    median_intake: Optional[float] = None
    days_with_data: int = 0
    target: Optional[float] = None
    target_type: Optional[str] = None  # "RDA" or "AI"
    pct_of_target: Optional[float] = None
    ul: Optional[float] = None
    ul_type: Optional[str] = None  # "UL" or "CDRR"
    note: Optional[str] = None


@dataclass
class DeficiencyReport:
    profile: UserProfile
    window: tuple[str, str]
    days_analyzed: int
    statuses: list[NutrientStatus] = field(default_factory=list)
    limitations: list[str] = field(default_factory=lambda: list(KNOWN_LIMITATIONS))

    def deficiencies(self, include_borderline: bool = True) -> list[NutrientStatus]:
        """Ranked worst-first: lowest % of target comes first."""
        wanted = {"deficient", "borderline"} if include_borderline else {"deficient"}
        ranked = [s for s in self.statuses if s.status in wanted]
        return sorted(ranked, key=lambda s: s.pct_of_target if s.pct_of_target is not None else 999)

    def excesses(self) -> list[NutrientStatus]:
        return [s for s in self.statuses if s.status == "excess"]

    def no_data(self) -> list[NutrientStatus]:
        return [s for s in self.statuses if s.status == "no_data"]


def analyze_deficiencies(nutrient_data: pd.DataFrame, profile: UserProfile) -> DeficiencyReport:
    """
    nutrient_data: tidy long-format DataFrame with columns date, nutrient,
        amount, unit — i.e. `ParsedNutritionData.daily` from parser.py.
    profile: UserProfile(age, sex)

    Averages intake across the window using the MEDIAN (more robust to one
    unusually high/low day than the mean), computes % of RDA/AI per
    nutrient, and classifies each as deficient / borderline / adequate /
    excess (or no_data if the export never logged that nutrient).
    """
    required_cols = {"date", "nutrient", "amount", "unit"}
    missing_cols = required_cols - set(nutrient_data.columns)
    if missing_cols:
        raise ValueError(f"nutrient_data is missing expected columns: {sorted(missing_cols)}")

    seen_nutrients = set(nutrient_data["nutrient"].unique())
    grouped = nutrient_data.groupby("nutrient")

    statuses: list[NutrientStatus] = []

    for nutrient, ref in DRI_TABLE.items():
        if nutrient not in seen_nutrients:
            statuses.append(NutrientStatus(
                nutrient=nutrient,
                unit=ref.unit,
                status="no_data",
                target_type=ref.target_type,
                note="Not present in this export.",
            ))
            continue

        sub = grouped.get_group(nutrient)
        median_intake = float(sub["amount"].median())
        days_with_data = int(sub["amount"].notna().sum())
        unit = sub["unit"].iloc[0]

        target = get_target(nutrient, profile.age, profile.sex)
        ul = get_ul(nutrient, profile.age)
        pct = (median_intake / target * 100) if target else None

        if ul is not None and median_intake > ul:
            status = "excess"
        elif pct is not None and pct < DEFICIENT_THRESHOLD * 100:
            status = "deficient"
        elif pct is not None and pct < BORDERLINE_THRESHOLD * 100:
            status = "borderline"
        else:
            status = "adequate"

        statuses.append(NutrientStatus(
            nutrient=nutrient,
            unit=unit,
            status=status,
            median_intake=median_intake,
            days_with_data=days_with_data,
            target=target,
            target_type=ref.target_type,
            pct_of_target=pct,
            ul=ul,
            ul_type=ref.ul_type,
            note=ref.note,
        ))

    if not nutrient_data.empty:
        window = (str(nutrient_data["date"].min()), str(nutrient_data["date"].max()))
        days_analyzed = int(nutrient_data["date"].nunique())
    else:
        window = ("", "")
        days_analyzed = 0

    return DeficiencyReport(
        profile=profile,
        window=window,
        days_analyzed=days_analyzed,
        statuses=statuses,
    )