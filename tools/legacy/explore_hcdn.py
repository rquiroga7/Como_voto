"""Explore the HCDN website to find the API for newer votaciones."""
import requests
import re
from bs4 import BeautifulSoup

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
})

# 1. Check if votacion IDs go higher - try some specific high numbers
print("=== Probing high votacion IDs ===")
test_ids = [200, 300, 500, 1000, 2000, 3000, 5000, 7000, 8000, 9000, 10000]
for vid in test_ids:
    try:
        resp = session.get(f"https://votaciones.hcdn.gob.ar/votacion/{vid}", timeout=10)
        has_content = "¿CÓMO VOTÓ?" in resp.text if resp.status_code == 200 else False
        print(f"  ID {vid:6d}: status={resp.status_code}, has_content={has_content}")
    except Exception as e:
        print(f"  ID {vid:6d}: error={e}")

# 2. Check the main page JS for API endpoints
print("\n=== Checking main page for API/JS clues ===")
resp = session.get("https://votaciones.hcdn.gob.ar/", timeout=10)
soup = BeautifulSoup(resp.text, 'lxml')

# Find all script tags
for script in soup.find_all('script'):
    src = script.get('src', '')
    if src:
        print(f"  Script src: {src}")
    text = script.string or ''
    if 'api' in text.lower() or 'proxy' in text.lower() or 'buscar' in text.lower() or 'acta' in text.lower():
        print(f"  Script with API refs (len={len(text)}):")
        # Find URLs in the script
        urls = re.findall(r'["\']([/a-zA-Z]+(?:proxy|api|buscar|acta|votacion)[/a-zA-Z]*)["\']', text, re.I)
        if urls:
            print(f"    URLs found: {urls}")
        # Find relevant lines
        for line in text.split('\n'):
            if any(kw in line.lower() for kw in ['proxy', 'api', 'buscar', 'acta', 'votacion', 'periodo']):
                print(f"    {line.strip()[:150]}")

# 3. Try common API patterns
print("\n=== Trying API endpoints ===")
api_paths = [
    "/proxy/buscar",
    "/api/actas",
    "/api/votaciones",
    "/proxy/actas",
    "/api/periodos",
    "/proxy/periodos",
]
for path in api_paths:
    try:
        url = f"https://votaciones.hcdn.gob.ar{path}"
        resp = session.get(url, timeout=10)
        print(f"  {path}: status={resp.status_code}, content-type={resp.headers.get('content-type','?')}, len={len(resp.text)}")
        if resp.status_code == 200 and len(resp.text) < 500:
            print(f"    Body: {resp.text[:200]}")
    except Exception as e:
        print(f"  {path}: error={e}")

# 4. Try POST to proxy/buscar 
print("\n=== POST to proxy/buscar ===")
try:
    resp = session.post("https://votaciones.hcdn.gob.ar/proxy/buscar",
                        json={"query": "", "pageSize": 5, "page": 0},
                        timeout=10)
    print(f"  POST JSON: status={resp.status_code}, len={len(resp.text)}")
    if resp.status_code == 200:
        print(f"    Body: {resp.text[:500]}")
except Exception as e:
    print(f"  POST JSON error: {e}")

try:
    resp = session.post("https://votaciones.hcdn.gob.ar/proxy/buscar",
                        data={"query": "", "pageSize": 5, "page": 0},
                        timeout=10)
    print(f"  POST form: status={resp.status_code}, len={len(resp.text)}")
    if resp.status_code == 200:
        print(f"    Body: {resp.text[:500]}")
except Exception as e:
    print(f"  POST form error: {e}")
