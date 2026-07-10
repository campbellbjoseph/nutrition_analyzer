"""
Local FDC data source -- load Foundation Foods / SR Legacy from downloaded
JSON dumps instead of hitting the live FoodData Central API.

This is a drop-in replacement for FDCClient: it exposes the same
search_food() / get_food_profile() methods, so build_food_pool() in
food_recommender.py works completely unchanged -- it doesn't know or care
whether it's talking to the network or to a file on disk.

Get the downloads at https://fdc.nal.usda.gov/download-datasets.html
("Foundation Foods" and/or "SR Legacy", JSON format).

Usage:
    client = LocalFDCClient(["FoodData_Central_foundation_food_json.json"])
    # or with both datasets for broader coverage:
    client = LocalFDCClient([
        "FoodData_Central_foundation_food_json.json",
        "FoodData_Central_sr_legacy_food_json.json",
    ])
    pool = build_food_pool(client, CANDIDATE_FOODS, cache_path=None)  # no cache needed, it's all local
"""
from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Optional

from food_recommender import ALLOWED_DATA_TYPES, FoodProfile, parse_food_profile

# The wrapper key FDC's full-download JSON uses, by data type. Used as the
# first guess when unwrapping a downloaded file; see _extract_food_list for
# the fallback if a file doesn't match either of these.
_KNOWN_TOP_LEVEL_KEYS = ["FoundationFoods", "SRLegacyFoods"]


def _extract_food_list(data, source_path: str) -> list[dict]:
    """FDC's downloadable JSON normally wraps the food list under a
    data-type-specific top-level key, e.g. {"FoundationFoods": [...]}.
    Handle that, a bare top-level list, or fail loudly with whatever keys
    we actually found -- so this is a one-line fix if USDA ever renames
    the wrapper, instead of a silent empty database."""
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in _KNOWN_TOP_LEVEL_KEYS:
            if key in data and isinstance(data[key], list):
                return data[key]
        # Fallback: grab the first list-of-food-dicts we can find, whatever
        # it's actually called.
        for key, value in data.items():
            if isinstance(value, list) and value and isinstance(value[0], dict) and "foodNutrients" in value[0]:
                return value
        raise ValueError(
            f"Couldn't find a food list in {source_path}. "
            f"Top-level keys found: {list(data.keys())} -- "
            "add whichever one of these is the food list to _KNOWN_TOP_LEVEL_KEYS."
        )

    raise ValueError(f"Unexpected JSON structure in {source_path} (expected a list or dict at the top level)")


def _normalize(text: str) -> str:
    return " ".join(text.lower().replace(",", " ").split())


def _food_category(food: dict) -> str:
    """FDC's category field is normally {"foodCategory": {"description": "..."}},
    but be tolerant of a bare string too, and of it being absent entirely
    (some Foundation Foods records don't carry one)."""
    category = food.get("foodCategory")
    if isinstance(category, dict):
        return (category.get("description") or "").strip()
    if isinstance(category, str):
        return category.strip()
    return ""


class LocalFoodDatabase:
    """Loads one or more FDC full-download JSON files into memory, indexed
    by fdcId and by normalized description for fast local lookup."""

    def __init__(self, json_paths: list[str], excluded_categories: Optional[set[str]] = None):
        self._by_id: dict[int, dict] = {}
        self._descriptions: list[tuple[str, int]] = []  # (normalized_description, fdc_id)
        self._excluded_categories = {c.strip().lower() for c in (excluded_categories or set()) if c.strip()}

        for path in json_paths:
            self._load_file(path)

        if not self._by_id:
            raise ValueError("No foods loaded -- check the JSON file path(s) and their contents")

    def _load_file(self, path: str) -> None:
        raw = json.loads(Path(path).read_text())
        foods = _extract_food_list(raw, path)
        print(self._excluded_categories)

        loaded = 0
        excluded = 0
        for food in foods:
            try:
                data_type = food.get("dataType", "")
                if data_type not in ALLOWED_DATA_TYPES:
                    continue  # defensive -- we expect single-data-type files, but don't assume it

                if self._excluded_categories and _food_category(food).lower() in self._excluded_categories:
                    excluded += 1
                    continue

                fdc_id = food.get("fdcId")
                description = food.get("description", "")
                if fdc_id is None or not description:
                    continue
                self._by_id[fdc_id] = food
                self._descriptions.append((_normalize(description), fdc_id))
                loaded += 1
            except AttributeError:
                pass

        excluded_note = f" ({excluded} excluded by category)" if excluded else ""
        print(f"Loaded {loaded} foods from {path}{excluded_note}")

    def get(self, fdc_id: int) -> Optional[dict]:
        return self._by_id.get(fdc_id)

    def all_foods(self) -> list[dict]:
        return list(self._by_id.values())

    def search(self, query: str, page_size: int = 3) -> list[dict]:
        """Return up to page_size best-matching raw food dicts for `query`.

        Exact normalized match wins outright. Otherwise, rank by TOKEN
        CONTAINMENT rather than plain character similarity: what fraction
        of the query's words appear in the candidate description. This
        matters because FDC descriptions (especially SR Legacy) are often
        long compound phrases -- "Chicken, broilers or fryers, breast,
        meat only, raw" -- while candidate queries are short common names
        like "chicken breast, raw". Character-ratio similarity penalizes
        that length mismatch even for an obviously-correct match; token
        containment doesn't, as long as the query's words are a subset of
        the description's. difflib similarity is used only as a tiebreaker
        among candidates that already clear the containment bar.
        """
        norm_query = _normalize(query)
        query_tokens = set(norm_query.split())
        if not query_tokens:
            return []

        desc_to_ids: dict[str, list[int]] = {}
        for desc, fdc_id in self._descriptions:
            desc_to_ids.setdefault(desc, []).append(fdc_id)

        if norm_query in desc_to_ids:
            return [self._by_id[fdc_id] for fdc_id in desc_to_ids[norm_query][:page_size]]

        containment_threshold = 0.6
        scored: list[tuple[float, float, str]] = []
        for desc in desc_to_ids:
            desc_tokens = set(desc.split())
            containment = len(query_tokens & desc_tokens) / len(query_tokens)
            if containment < containment_threshold:
                continue
            similarity = difflib.SequenceMatcher(None, norm_query, desc).ratio()
            scored.append((containment, similarity, desc))

        scored.sort(key=lambda t: (t[0], t[1]), reverse=True)

        results = []
        for _, _, desc in scored[:page_size]:
            for fdc_id in desc_to_ids[desc]:
                results.append(self._by_id[fdc_id])
        return results[:page_size]


class LocalFDCClient:
    """Drop-in replacement for FDCClient, backed by local JSON downloads
    instead of the live FoodData Central API. Same search_food() /
    get_food_profile() interface -- build_food_pool() doesn't need to
    change at all to use this instead of the networked client."""

    def __init__(self, json_paths: list[str], excluded_categories: Optional[set[str]] = None):
        self.db = LocalFoodDatabase(json_paths, excluded_categories=excluded_categories)

    def search_food(self, query: str, page_size: int = 3) -> Optional[dict]:
        matches = self.db.search(query, page_size=page_size)
        if not matches:
            return None
        # Same priority as the live API path: Foundation over SR Legacy.
        matches.sort(key=lambda f: 0 if f.get("dataType") == "Foundation" else 1)
        return matches[0]

    def get_food_profile(self, fdc_id: int, description: str = "", data_type: str = "") -> FoodProfile:
        food = self.db.get(fdc_id)
        if food is None:
            raise KeyError(f"fdcId {fdc_id} not found in local database")
        return parse_food_profile(
            food, description or food.get("description", ""), data_type or food.get("dataType", "")
        )

    def all_food_profiles(self) -> list[FoodProfile]:
        """Convert every loaded food directly into a FoodProfile, skipping
        the name-search/match step entirely. Use this when you want the
        whole downloaded database as recommendation candidates rather than
        a curated name list (e.g. CANDIDATE_FOODS) -- there's no need to
        "look up" foods you already have fully loaded in memory."""
        return [
            parse_food_profile(food, food.get("description", ""), food.get("dataType", ""))
            for food in self.db.all_foods()
        ]


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python3 local_food_data.py <foundation.json> [sr_legacy.json ...]")
        sys.exit(1)

    client = LocalFDCClient(sys.argv[1:])
    match = client.search_food("spinach, raw")
    print("Best match:", match.get("description") if match else None)
    if match:
        profile = client.get_food_profile(match["fdcId"], match.get("description", ""), match.get("dataType", ""))
        print("kcal/100g:", profile.kcal_per_100g)
        print("Nutrients found:", profile.nutrients_per_100g)