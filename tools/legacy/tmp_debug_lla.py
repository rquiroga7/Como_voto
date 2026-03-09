"""Debug why LLA bloc members end up as OTROS."""
import sys
sys.path.insert(0, 'tools')
from generate_site import _classify_bloc_for_term, _era_coalition, _normalize_bloc_display

# Test the classification chain
bloc_name = "La Libertad Avanza"
year = 2024

base = _classify_bloc_for_term(bloc_name, year)
era = _era_coalition(base, year)
norm = _normalize_bloc_display(bloc_name)

print(f"bloc_name={bloc_name!r}")
print(f"_classify_bloc_for_term('{bloc_name}', {year}) = {base!r}")
print(f"_era_coalition({base!r}, {year}) = {era!r}")
print(f"_normalize_bloc_display('{bloc_name}') = {norm!r}")

# Also test with the raw name that might come from DB
for raw in ["LA LIBERTAD AVANZA", "la libertad avanza", "La Libertad Avanza"]:
    base = _classify_bloc_for_term(raw, year)
    era = _era_coalition(base, year)
    print(f"  raw={raw!r} -> base={base!r} -> era={era!r}")
