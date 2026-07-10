"""
Offline tests for food_recommender.py that don't require network access:
1. parse_food_profile() against two synthetic FDC-shaped JSON payloads (the
   flat shape /foods/search tends to return, and the nested shape /food/{id}
   tends to return) to confirm both are parsed identically.
2. recommend_foods() against your REAL deficiency report from Phase 2 plus a
   handful of synthetic FoodProfiles with plausible (but approximate, for
   testing only) nutrient values, to sanity-check the greedy coverage logic.

This does NOT verify the actual FDC API integration (search_food /
get_food_profile's live HTTP calls) -- that needs a real API key, run
food_recommender.py's __main__ block yourself to smoke-test that part.
"""
from parser import parse_cronometer_csv
from analyzer import UserProfile, analyze_deficiencies
from food_recommender import parse_food_profile, recommend_foods, FoodProfile, build_food_pool

# --- 1. parsing: flat shape (typical of /foods/search) ---------------------
flat_payload = {
    "fdcId": 123,
    "foodNutrients": [
        {"nutrientName": "Energy", "unitName": "KCAL", "amount": 23},
        {"nutrientName": "Vitamin K (phylloquinone)", "unitName": "UG", "amount": 483},
        {"nutrientName": "Vitamin A, RAE", "unitName": "UG", "amount": 469},
        {"nutrientName": "Iron, Fe", "unitName": "MG", "amount": 2.71},
        {"nutrientName": "Folate, DFE", "unitName": "UG", "amount": 194},
    ],
}

# --- 2. ranking logic against your real Phase 2 report ----------------------
result = parse_cronometer_csv("dailysummary-test.csv")
profile = UserProfile(age=34, sex="male")
report = analyze_deficiencies(result.daily, profile)

print()
print("Deficient/borderline nutrients being targeted:")
for s in report.deficiencies():
    print(f"  {s.nutrient:12s} {s.pct_of_target:5.1f}% of {s.target_type}")

foods = build_food_pool()

recs = recommend_foods(report, synthetic_pool, top_n=4)
print()
print("Top recommendations (greedy coverage):")
for r in recs:
    addressed_str = ", ".join(f"{n} {pct:.0f}%" for n, pct in r.addressed)
    print(f"  {r.food.description:38s} score={r.coverage_score:.2f}  addresses: {addressed_str}")

assert len(recs) > 0, "expected at least one recommendation"
# kale should rank at or near the top: it's the only food hitting our worst
# deficiency (vitamin_k at 21%) hard, plus it's cheap on calories.
assert recs[0].food.description.startswith("kale"), f"expected kale first, got {recs[0].food.description}"
print()
print("[OK] recommend_foods greedily prioritizes coverage of the worst deficiencies")