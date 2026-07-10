"""
Phase 3 -- Food recommendation engine.

Given a DeficiencyReport (Phase 2) and a pool of candidate whole foods, this
ranks foods scored per calorie (not per 100g -- so we never end up
recommending "eat 2,000 calories of liver" to fix one vitamin), then greedily
picks foods that cover the widest SPREAD of different deficiencies rather
than five foods that all happen to help the same one nutrient.

Talks to USDA FoodData Central (FDC) -- restricted to Foundation Foods + SR
Legacy only (single-ingredient whole foods; Branded/Survey(FNDDS) datasets
are deliberately excluded since those are packaged products / mixed dishes).
Get a free key at https://api.data.gov/signup/ and either set it as the
FDC_API_KEY environment variable or pass api_key=... directly.

*** This module has NOT been tested against the live FDC API in this
environment (no network access in this sandbox). The nutrient-matching and
coverage-ranking logic IS tested here (see test_food_recommender.py) using
synthetic food data, but the actual HTTP calls need a smoke test on your
end -- see the __main__ block at the bottom for a one-food sanity check. ***
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests

from analyzer import DeficiencyReport, NutrientStatus

FDC_BASE_URL = "https://api.nal.usda.gov/fdc/v1"
ALLOWED_DATA_TYPES = ["Foundation", "SR Legacy"]
ENERGY_NAME = "energy"

# canonical_key -> FDC nutrient name(s) to look for, in priority order (first
# match wins). Matched by NAME rather than FDC's numeric "number"/"id" fields,
# since those are inconsistent across API response shapes (search vs. detail
# endpoints) -- names are the stable, documented part of the API.
NUTRIENT_FDC_NAME_MAP: dict[str, list[str]] = {
    "vitamin_b1": ["Thiamin"],
    "vitamin_b2": ["Riboflavin"],
    "vitamin_b3": ["Niacin"],
    "vitamin_b5": ["Pantothenic acid"],
    "vitamin_b6": ["Vitamin B-6", "Vitamin B6"],
    "vitamin_b12": ["Vitamin B-12", "Vitamin B12"],
    "folate": ["Folate, DFE", "Folate, total"],
    "vitamin_a": ["Vitamin A, RAE"],
    "vitamin_c": ["Vitamin C, total ascorbic acid", "Vitamin C"],
    "vitamin_d": ["Vitamin D (D2 + D3)", "Vitamin D"],
    "vitamin_e": ["Vitamin E (alpha-tocopherol)", "Vitamin E"],
    "vitamin_k": ["Vitamin K (phylloquinone)", "Vitamin K"],
    "calcium": ["Calcium, Ca"],
    "copper": ["Copper, Cu"],
    "iron": ["Iron, Fe"],
    "magnesium": ["Magnesium, Mg"],
    "manganese": ["Manganese, Mn"],
    "phosphorus": ["Phosphorus, P"],
    "potassium": ["Potassium, K"],
    "selenium": ["Selenium, Se"],
    "sodium": ["Sodium, Na"],
    "zinc": ["Zinc, Zn"],
}

# A curated pool of common, single-ingredient whole foods to look up on FDC,
# spanning produce, meat/fish, dairy/eggs, legumes/nuts/seeds, and grains.
# These are food NAMES, not memorized FDC IDs -- the actual ID is resolved
# live via search, so this list stays correct even as FDC's database changes.
CANDIDATE_FOODS: list[str] = [
    "spinach, raw", "kale, raw", "swiss chard, raw",
    "brussels sprouts, raw", "red bell pepper, raw", "sweet potato, raw",
    "carrots, raw", "butternut squash, raw", "mushrooms, portabella, raw",
    "mushrooms, maitake, raw", "tomato, roma", "avocado, raw",
    "oranges, raw, navel", "kiwifruit, raw", "strawberries, raw", "banana, raw",
    "salmon, atlantic, wild, raw", "sardines, canned in oil", "tuna, raw",
    "mackerel, raw", "trout, raw", "shrimp, raw", "oysters, raw", "clams, raw",
    "beef liver, raw", "chicken liver, raw", "beef, ground, 85% lean, raw",
    "chicken breast, raw", "turkey breast, raw", "pork chop, raw",
    "eggs, whole, raw", "Milk, whole, 3.25% milkfat, with added vitamin D", "Yogurt, Greek, plain, whole milk", "Cheese, cheddar, sharp, sliced",
    "cottage cheese", "almonds, raw", "walnuts, raw", "brazil nuts, raw",
    "sunflower seeds, raw", "pumpkin seeds, raw", "cashews, raw",
    "lentils, raw", "chickpeas, raw", "black beans, raw", "tofu, raw",
    "edamame, raw", "quinoa, raw", "oats, raw", "brown rice, raw",
    "whole wheat bread", "sweet potato, baked",
]


@dataclass
class FoodProfile:
    fdc_id: Optional[int]
    description: str
    data_type: str
    kcal_per_100g: Optional[float]
    nutrients_per_100g: dict[str, float]  # canonical_key -> amount per 100g


@dataclass
class FoodRecommendation:
    food: FoodProfile
    coverage_score: float
    addressed: list[tuple[str, float]]  # (nutrient, % of daily target one serving closes)


class FDCClient:
    """Thin wrapper around the FoodData Central REST API."""

    def __init__(self, api_key: Optional[str] = None, session: Optional[requests.Session] = None):
        self.api_key = api_key or os.environ.get("FDC_API_KEY")
        if not self.api_key:
            raise ValueError(
                "No FDC API key found. Get a free one at https://api.data.gov/signup/ "
                "and pass api_key=... or set the FDC_API_KEY environment variable."
            )
        self.session = session or requests.Session()

    def search_food(self, query: str, page_size: int = 3) -> Optional[dict]:
        """Return the best-matching Foundation/SR Legacy food for `query`, or None."""
        resp = self.session.get(
            f"{FDC_BASE_URL}/foods/search",
            params={
                "api_key": self.api_key,
                "query": query,
                # GET expects a comma-joined string here (the JSON-array form
                # is for POST request bodies); passing a list would make
                # `requests` emit repeated dataType= params instead.
                "dataType": ",".join(ALLOWED_DATA_TYPES),
                "pageSize": page_size,
            },
            timeout=15,
        )
        resp.raise_for_status()
        foods = resp.json().get("foods", [])
        if not foods:
            return None
        # Prefer Foundation Foods (more rigorous, ongoing analysis) over SR Legacy.
        foods.sort(key=lambda f: 0 if f.get("dataType") == "Foundation" else 1)
        return foods[0]

    def get_food_profile(self, fdc_id: int, description: str = "", data_type: str = "") -> FoodProfile:
        resp = self.session.get(
            f"{FDC_BASE_URL}/food/{fdc_id}",
            params={"api_key": self.api_key},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return parse_food_profile(
            data, description or data.get("description", ""), data_type or data.get("dataType", "")
        )


def _extract_nutrient_name(entry: dict) -> str:
    # /food/{id} nests under entry["nutrient"]["name"]; /foods/search often
    # flattens to entry["nutrientName"]. Handle both defensively.
    if isinstance(entry.get("nutrient"), dict):
        return entry["nutrient"].get("name") or ""
    return entry.get("nutrientName") or entry.get("name") or ""


def _extract_nutrient_unit(entry: dict) -> str:
    if isinstance(entry.get("nutrient"), dict):
        return (entry["nutrient"].get("unitName") or "").lower()
    return (entry.get("unitName") or "").lower()


def _extract_nutrient_amount(entry: dict) -> Optional[float]:
    amount = entry.get("amount")
    if amount is None:
        return None
    try:
        return float(amount)
    except (TypeError, ValueError):
        return None


# canonical_key -> (target_unit, {source_unit_lowercase: factor_to_target_unit})
# FDC sometimes reports a nutrient with the SAME display name under two unit
# systems for a given food (vitamin D notably has both a mcg-based entry and
# an IU-based entry, both literally named "Vitamin D (D2 + D3)" in some
# records). Since matching happens by name, an entry landing in an
# unexpected unit needs an explicit conversion -- or to be skipped outright
# -- rather than being blindly treated as if it were already in the target
# unit. Without this, a food could get silently compared against an RDA
# target using the wrong scale (IU treated as mcg is off by ~40x).
NUTRIENT_UNIT_CONVERSIONS: dict[str, tuple[str, dict[str, float]]] = {
    # 1 IU vitamin D3 = 0.025 mcg cholecalciferol
    "vitamin_d": ("mcg", {"µg": 1.0, "ug": 1.0, "mcg": 1.0, "iu": 0.025}),
}


def parse_food_profile(data: dict, description: str, data_type: str) -> FoodProfile:
    """Turn a raw /food/{id} JSON payload into a FoodProfile."""
    food_nutrients = data.get("foodNutrients", [])

    kcal: Optional[float] = None
    nutrients: dict[str, float] = {}

    for entry in food_nutrients:
        name = _extract_nutrient_name(entry).strip()
        amount = _extract_nutrient_amount(entry)
        if amount is None or not name:
            continue

        if name.lower() == ENERGY_NAME and _extract_nutrient_unit(entry) == "kcal":
            kcal = amount
            continue

        for canonical_key, name_options in NUTRIENT_FDC_NAME_MAP.items():
            if canonical_key in nutrients:
                continue  # already matched a higher-priority name for this key
            if not any(name.lower() == wanted.lower() for wanted in name_options):
                continue

            conversion = NUTRIENT_UNIT_CONVERSIONS.get(canonical_key)
            if conversion is not None:
                _target_unit, factors = conversion
                unit = _extract_nutrient_unit(entry)
                factor = factors.get(unit)
                if factor is None:
                    print(
                        f"Note: {canonical_key} entry for {description!r} has unexpected "
                        f"unit {unit!r} -- skipping this entry rather than risk a wrong-scale value."
                    )
                    continue
                amount = amount * factor

            nutrients[canonical_key] = amount
            break

    return FoodProfile(
        fdc_id=data.get("fdcId"),
        description=description,
        data_type=data_type,
        kcal_per_100g=kcal,
        nutrients_per_100g=nutrients,
    )


def build_food_pool(
    client: FDCClient,
    candidate_names: list[str] = CANDIDATE_FOODS,
    cache_path: Optional[str] = "fdc_cache.json",
    request_delay_seconds: float = 0.0,
) -> list[FoodProfile]:
    """
    Look up each candidate name on FDC and return their nutrient profiles.
    Caches results to `cache_path` (JSON) so repeat runs don't re-hit the
    API -- FDC's default rate limit is 1,000 requests/hour per key.
    """
    cache: dict[str, dict] = {}
    cache_file = Path(cache_path) if cache_path else None
    if cache_file and cache_file.exists():
        cache = json.loads(cache_file.read_text())

    profiles: list[FoodProfile] = []
    dirty = False

    for name in candidate_names:
        if name in cache:
            profiles.append(FoodProfile(**cache[name]))
            continue

        try:
            match = client.search_food(name)
            if match is None:
                print(f"Note: no Foundation/SR Legacy match found for {name!r}, skipping.")
                continue

            profile = client.get_food_profile(
                match["fdcId"], description=match.get("description", name), data_type=match.get("dataType", "")
            )
        except requests.exceptions.RequestException as e:
            # One bad food (404 on a stale/retired fdcId, a timeout, etc.)
            # shouldn't take down the other ~50 lookups in this batch.
            # Deliberately NOT cached, so it's retried on the next run rather
            # than being permanently skipped.
            print(f"Note: FDC lookup failed for {name!r} ({e}), skipping.")
            continue

        profiles.append(profile)
        cache[name] = profile.__dict__
        dirty = True
        if request_delay_seconds:
            time.sleep(request_delay_seconds)

    if cache_file and dirty:
        cache_file.write_text(json.dumps(cache, indent=2))

    return profiles


def _severity_weight(status: NutrientStatus) -> float:
    """Bigger = more urgent. A nutrient at 0% of target counts more than one at 90%."""
    if status.pct_of_target is None:
        return 0.0
    shortfall = max(0.0, 100.0 - status.pct_of_target) / 100.0
    return min(shortfall, 1.5)  # capped so a totally-absent nutrient doesn't swamp the score


# See the comment at its use site in recommend_foods() for why this floor exists.
_MIN_REMAINING_WEIGHT_FRACTION = 0.15


def recommend_foods(
    report: DeficiencyReport,
    food_pool: list[FoodProfile],
    top_n: int = 6,
    serving_grams: float = 100.0,
) -> list[FoodRecommendation]:
    """
    Greedy coverage ranking over your current deficient/borderline nutrients:
    repeatedly pick whichever remaining food adds the most weighted value,
    then discount the nutrients it just covered before picking the next one
    -- so recommendation #2 is rewarded for covering something DIFFERENT
    from #1, rather than just being the second-best source of the same thing.
    """
    deficiencies = report.deficiencies(include_borderline=True)
    if not deficiencies or not food_pool:
        return []

    remaining_weight = {s.nutrient: _severity_weight(s) for s in deficiencies}
    target_by_nutrient = {s.nutrient: s.target for s in deficiencies}

    picked: list[FoodRecommendation] = []
    pool = list(food_pool)

    for _ in range(min(top_n, len(pool))):
        best_food, best_score, best_addressed = None, 0.0, []

        for food in pool:
            if not food.kcal_per_100g:
                continue
            score = 0.0
            addressed: list[tuple[str, float]] = []
            for nutrient, weight in remaining_weight.items():
                if weight <= 0:
                    continue
                amount_per_100g = food.nutrients_per_100g.get(nutrient)
                target = target_by_nutrient.get(nutrient)
                if amount_per_100g is None or not target:
                    continue
                per_serving = amount_per_100g * (serving_grams / 100.0)
                # capped at 100%: eating one giant serving of a single food
                # doesn't get credit for "200% of today's target" of anything
                pct_closed = min(per_serving / target, 1.0)
                if pct_closed <= 0:
                    continue
                score += weight * pct_closed
                addressed.append((nutrient, pct_closed * 100))

            if score > best_score:
                best_food, best_score, best_addressed = food, score, addressed

        if best_food is None:
            break

        picked.append(FoodRecommendation(food=best_food, coverage_score=best_score, addressed=best_addressed))
        pool.remove(best_food)

        for nutrient, pct_closed in best_addressed:
            # Discount, don't zero out: a fully-closed nutrient (pct_closed
            # == 100) still keeps a small residual weight rather than
            # dropping to exactly 0. Without this floor, a single
            # concentrated food (organ meats, shellfish -- common in SR
            # Legacy) can single-handedly saturate every deficient nutrient
            # in 1-2 picks, at which point every remaining food scores
            # exactly 0 and the loop stops dead, ignoring --top-n entirely.
            # The residual keeps secondary/tertiary sources for the same
            # nutrient rankable (at sharply diminished value), so the
            # recommendation list actually fills out to top_n when the pool
            # supports it.
            remaining_weight[nutrient] *= max(_MIN_REMAINING_WEIGHT_FRACTION, 1.0 - pct_closed / 100.0)

    return picked


if __name__ == "__main__":
    # Quick one-food smoke test to run locally once you have an API key:
    #   export FDC_API_KEY=your_key_here
    #   python3 food_recommender.py
    client = FDCClient()
    match = client.search_food("spinach, raw")
    print("Best match:", match.get("description") if match else None)
    if match:
        profile = client.get_food_profile(match["fdcId"], match.get("description", ""), match.get("dataType", ""))
        print("kcal/100g:", profile.kcal_per_100g)
        print("Nutrients found:", profile.nutrients_per_100g)