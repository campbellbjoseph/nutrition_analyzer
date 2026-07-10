"""
Dietary Reference Intake (DRI) reference table.

Source: National Academies of Sciences, Engineering, and Medicine, Food and
Nutrition Board — "Dietary Reference Intakes Summary Tables" (Appendix J of
Dietary Reference Intakes for Sodium and Potassium, 2019), reproduced by
NIH/NCBI Bookshelf: https://www.ncbi.nlm.nih.gov/books/NBK545442/
These are public-domain U.S. government figures, safe to hardcode.

Covers adults only (age 19+), split into the four DRI adult age bands:
19-30, 31-50, 51-70, and 71+. Pregnancy/lactation values are NOT included —
this table assumes a non-pregnant, non-lactating adult.

Two kinds of "target" exist in the DRI framework:
  - RDA (Recommended Dietary Allowance): backed by enough evidence to say
    "meets the needs of ~97-98% of healthy people in this group."
  - AI (Adequate Intake): used when there isn't enough evidence for a true
    RDA; a reasonable goal, but with less certainty behind the number.

`target_type` on each entry tells you which kind you're looking at — an
"AI" miss is a softer signal than an "RDA" miss.

UL = Tolerable Upper Intake Level (usual meaning: unlikely to cause harm
even if regularly exceeded). Sodium is the one exception: it has no true
UL, so we store its 2,300 mg/day Chronic Disease Risk Reduction (CDRR)
target instead and mark ul_type="CDRR" — crossing it is a "you're at the
high end of recommended, consider easing off" signal, not a safety alarm.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Age bands used throughout this table, in order.
AGE_BANDS: list[tuple[int, int]] = [(19, 30), (31, 50), (51, 70), (71, 200)]


@dataclass(frozen=True)
class NutrientReference:
    unit: str
    target_type: str  # "RDA" or "AI"
    male: tuple[float, float, float, float]
    female: tuple[float, float, float, float]
    ul: Optional[tuple[float, float, float, float]] = None
    ul_type: str = "UL"  # "UL" or "CDRR"
    ul_note: Optional[str] = None
    note: Optional[str] = None


def _const(value: float) -> tuple[float, float, float, float]:
    """Helper for values that don't change across adult age bands."""
    return (value, value, value, value)


# Keys match parser.py's VITAMIN_MINERAL_ALIASES canonical nutrient keys.
DRI_TABLE: dict[str, NutrientReference] = {
    "vitamin_b1": NutrientReference(
        unit="mg", target_type="RDA", male=_const(1.2), female=_const(1.1),
        ul_note="No UL established (insufficient data on adverse effects).",
    ),
    "vitamin_b2": NutrientReference(
        unit="mg", target_type="RDA", male=_const(1.3), female=_const(1.1),
        ul_note="No UL established.",
    ),
    "vitamin_b3": NutrientReference(
        unit="mg", target_type="RDA", male=_const(16), female=_const(14),
        ul=_const(35),
        note=(
            "DRI is expressed as niacin equivalents (NE, accounting for "
            "tryptophan conversion); Cronometer reports preformed niacin, "
            "so this comparison slightly understates true niacin status."
        ),
        ul_note="UL applies to synthetic/supplemental niacin, not food sources.",
    ),
    "vitamin_b5": NutrientReference(
        unit="mg", target_type="RDA", male=_const(5), female=_const(5),
        ul_note="No UL established.",
    ),
    "vitamin_b6": NutrientReference(
        unit="mg", target_type="RDA",
        male=(1.3, 1.3, 1.7, 1.7), female=(1.3, 1.3, 1.5, 1.5),
        ul=_const(100),
    ),
    "vitamin_b12": NutrientReference(
        unit="mcg", target_type="RDA", male=_const(2.4), female=_const(2.4),
        note=(
            "After age 50, absorption of food-bound B12 declines; the RDA "
            "is best met via fortified foods or a supplement at that point."
        ),
        ul_note="No UL established.",
    ),
    "folate": NutrientReference(
        unit="mcg", target_type="RDA", male=_const(400), female=_const(400),
        ul=_const(1000),
        ul_note=(
            "UL applies to synthetic folic acid from supplements/fortified "
            "food, not natural food folate."
        ),
    ),
    "vitamin_a": NutrientReference(
        unit="mcg", target_type="RDA", male=_const(900), female=_const(700),
        ul=_const(3000),
        ul_note="UL applies to preformed vitamin A only, not provitamin-A carotenoids.",
    ),
    "vitamin_c": NutrientReference(
        unit="mg", target_type="RDA", male=_const(90), female=_const(75),
        ul=_const(2000),
    ),
    "vitamin_d": NutrientReference(
        unit="mcg", target_type="RDA",
        male=(15, 15, 15, 20), female=(15, 15, 15, 20),
        ul=_const(100),
    ),
    "vitamin_e": NutrientReference(
        unit="mg", target_type="RDA", male=_const(15), female=_const(15),
        ul=_const(1000),
        ul_note="UL applies to supplemental alpha-tocopherol, not food sources.",
    ),
    "vitamin_k": NutrientReference(
        unit="mcg", target_type="RDA", male=_const(120), female=_const(90),
        ul_note="No UL established.",
    ),
    "calcium": NutrientReference(
        unit="mg", target_type="RDA",
        male=(1000, 1000, 1000, 1200), female=(1000, 1000, 1200, 1200),
        ul=(2500, 2500, 2000, 2000),
        ul_note="UL drops from 2,500 to 2,000 mg/day after age 50.",
    ),
    "copper": NutrientReference(
        unit="mg", target_type="RDA", male=_const(0.9), female=_const(0.9),
        ul=_const(10),
    ),
    "iron": NutrientReference(
        unit="mg", target_type="RDA",
        male=_const(8), female=(18, 18, 8, 8),
        ul=_const(45),
        note="Women's RDA drops from 18 to 8 mg/day after age 50 (post-menopause).",
    ),
    "magnesium": NutrientReference(
        unit="mg", target_type="RDA",
        male=(400, 420, 420, 420), female=(310, 320, 320, 320),
        ul=_const(350),
        ul_note=(
            "UL applies to supplemental/pharmacological magnesium only, not "
            "food sources — food-source magnesium has no established UL."
        ),
    ),
    "manganese": NutrientReference(
        unit="mg", target_type="RDA", male=_const(2.3), female=_const(1.8),
        ul=_const(11),
    ),
    "phosphorus": NutrientReference(
        unit="mg", target_type="RDA", male=_const(700), female=_const(700),
        ul=(4000, 4000, 4000, 3000),
        ul_note="UL drops from 4,000 to 3,000 mg/day after age 70.",
    ),
    "potassium": NutrientReference(
        unit="mg", target_type="RDA", male=_const(3400), female=_const(2600),
        note="No UL established; most people fall short of this rather than exceed it.",
    ),
    "selenium": NutrientReference(
        unit="mcg", target_type="RDA", male=_const(55), female=_const(55),
        ul=_const(400),
    ),
    "sodium": NutrientReference(
        unit="mg", target_type="RDA", male=_const(1500), female=_const(1500),
        ul=_const(2300), ul_type="CDRR",
        ul_note=(
            "2,300 mg/day is a Chronic Disease Risk Reduction (CDRR) target "
            "tied to blood-pressure risk, not a toxicity threshold. Crossing "
            "it flags 'above the recommended ceiling,' not danger."
        ),
    ),
    "zinc": NutrientReference(
        unit="mg", target_type="RDA", male=_const(11), female=_const(8),
        ul=_const(40),
    ),
}

# Nutrients Cronometer/parser.py can track but that don't have a reliable
# reference value or export column worth trusting.
KNOWN_LIMITATIONS: list[str] = [
    "Iodine is not included in this export at all — Cronometer's iodine "
    "tracking is widely considered unreliable (intake is soil-dependent and "
    "rarely tested in food databases), so its absence here isn't a bug.",
    "Niacin is compared against food-only niacin rather than niacin "
    "equivalents (NE), which factor in conversion from dietary tryptophan — "
    "true niacin status is very likely slightly better than shown.",
]


def _band_index(age: int) -> int:
    if age < AGE_BANDS[0][0]:
        raise ValueError(
            f"This reference table only covers adults (age {AGE_BANDS[0][0]}+); got age={age}."
        )
    for i, (lo, hi) in enumerate(AGE_BANDS):
        if lo <= age <= hi:
            return i
    return len(AGE_BANDS) - 1  # age is above the highest band's hi (shouldn't happen, band is open-ended)


def _normalize_sex(sex: str) -> str:
    s = sex.strip().lower()
    if s in ("m", "male"):
        return "male"
    if s in ("f", "female"):
        return "female"
    raise ValueError(f"sex must be 'male' or 'female', got {sex!r}")


def get_target(nutrient: str, age: int, sex: str) -> Optional[float]:
    """RDA or AI value for this nutrient/age/sex, or None if nutrient is unknown."""
    ref = DRI_TABLE.get(nutrient)
    if ref is None:
        return None
    idx = _band_index(age)
    values = ref.male if _normalize_sex(sex) == "male" else ref.female
    return values[idx]


def get_ul(nutrient: str, age: int) -> Optional[float]:
    """Tolerable Upper Intake Level (or CDRR for sodium) for this nutrient/age, or None."""
    ref = DRI_TABLE.get(nutrient)
    if ref is None or ref.ul is None:
        return None
    idx = _band_index(age)
    return ref.ul[idx]