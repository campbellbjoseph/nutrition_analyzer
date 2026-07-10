from parser import parse_cronometer_csv
from analyzer import UserProfile, analyze_deficiencies

result = parse_cronometer_csv('dailysummary-test.csv')
profile = UserProfile(age=23, sex='male')
report = analyze_deficiencies(result.daily, profile)

print(f'Window: {report.window}, days analyzed: {report.days_analyzed}')
print()
print('=== DEFICIENCIES / BORDERLINE (worst first) ===')
for s in report.deficiencies():
    print(f'{s.nutrient:14s} {s.median_intake:8.2f} {s.unit:4s} vs target {s.target:8.2f} ({s.target_type})  -> {s.pct_of_target:5.1f}%  [{s.status}]')

print()
print('=== EXCESS ===')
for s in report.excesses():
    print(f'{s.nutrient:14s} {s.median_intake:8.2f} {s.unit:4s} vs UL {s.ul:8.2f} ({s.ul_type})  [{s.status}]')

print()
print('=== ADEQUATE ===')
for s in report.statuses:
    if s.status == 'adequate':
        print(f'{s.nutrient:14s} {s.median_intake:8.2f} {s.unit:4s} vs target {s.target:8.2f}  -> {s.pct_of_target:5.1f}%')

print()
print('=== NO DATA ===')
for s in report.no_data():
    print(s.nutrient)