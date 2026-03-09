"""Probe HCDN votacion ID ranges to find all valid ranges."""
import requests
import time
import re

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
})

def check_id(vid):
    """Check if a votacion ID has content. Returns (has_content, date_snippet)."""
    try:
        resp = session.get(f"https://votaciones.hcdn.gob.ar/votacion/{vid}", timeout=10)
        if resp.status_code == 200 and "¿CÓMO VOTÓ?" in resp.text:
            # Extract date
            m = re.search(r'(\d{2}/\d{2}/\d{4})', resp.text)
            date = m.group(1) if m else '?'
            return True, date
        return False, None
    except:
        return False, None

# Probe systematically: check every 10th ID from 170 to 5000
print("=== Probing every 10th ID from 170 to 5000 ===")
ranges = []
last_valid = None

for vid in range(170, 5001, 10):
    valid, date = check_id(vid)
    if valid:
        if last_valid is None or vid - last_valid > 20:
            print(f"  NEW RANGE starting near ID {vid}: date={date}")
        last_valid = vid
        ranges.append((vid, date))
    time.sleep(0.2)

print(f"\nFound {len(ranges)} valid IDs (sampled every 10)")

# Group by year
by_year = {}
for vid, date in ranges:
    m = re.search(r'(\d{4})', date) if date else None
    yr = m.group(1) if m else '?'
    if yr not in by_year:
        by_year[yr] = []
    by_year[yr].append(vid)

print("\nID ranges by year:")
for yr in sorted(by_year.keys()):
    ids = by_year[yr]
    print(f"  {yr}: IDs {min(ids)}-{max(ids)} ({len(ids)} sampled)")

# Now probe more densely in the upper range to find the max
if ranges:
    max_sampled = max(r[0] for r in ranges)
    print(f"\nHighest sampled valid ID: {max_sampled}")
    print("Probing above that...")
    for vid in range(max_sampled, max_sampled + 200, 5):
        valid, date = check_id(vid)
        if valid:
            print(f"  ID {vid}: valid, date={date}")
        time.sleep(0.15)
