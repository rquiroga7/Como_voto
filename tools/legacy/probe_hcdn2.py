"""Probe for 2024-2026 HCDN data and find the true maximum ID."""
import requests
import time
import re

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
})

def check_id(vid):
    try:
        resp = session.get(f"https://votaciones.hcdn.gob.ar/votacion/{vid}", timeout=10)
        if resp.status_code == 200 and "¿CÓMO VOTÓ?" in resp.text:
            m = re.search(r'(\d{2}/\d{2}/\d{4})', resp.text)
            date = m.group(1) if m else '?'
            return True, date
        return False, None
    except:
        return False, None

# Check IDs from 4870 to 6000 densely
print("=== Dense probe: IDs 4870-6000 (every 5) ===")
for vid in range(4870, 6001, 5):
    valid, date = check_id(vid)
    if valid:
        print(f"  ID {vid}: date={date}")
    time.sleep(0.15)

# Also check very high IDs in case they jumped
print("\n=== Checking IDs 6000-10000 (every 50) ===")
for vid in range(6000, 10001, 50):
    valid, date = check_id(vid)
    if valid:
        print(f"  ID {vid}: date={date}")
    time.sleep(0.15)

# Check even higher
print("\n=== Checking IDs 10000-20000 (every 200) ===")
for vid in range(10000, 20001, 200):
    valid, date = check_id(vid)
    if valid:
        print(f"  ID {vid}: date={date}")
    time.sleep(0.15)
