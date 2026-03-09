"""Find the exact current max HCDN ID and count valid IDs near the top."""
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

# Dense check from 5860 to 5920
print("=== Finding exact max ID (5860-5920) ===")
max_valid = 0
for vid in range(5855, 5920):
    valid, date = check_id(vid)
    if valid:
        print(f"  ID {vid}: date={date}")
        max_valid = vid
    time.sleep(0.15)

print(f"\nMax valid ID: {max_valid}")
