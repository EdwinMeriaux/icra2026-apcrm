"""
Diagnostic: dump enough of the HTML structure to figure out why the
main scraper is missing papers. Run once and paste the output back.

    python inspect_icra.py
"""

import re
import requests
from bs4 import BeautifulSoup

URL = "https://ras.papercept.net/conferences/conferences/ICRA26/program/ICRA26_ContentListWeb_3.html"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

html = requests.get(URL, headers=HEADERS, timeout=60).text
print(f"raw html length: {len(html)}")

# How many paper IDs actually exist on the page?
ids = re.findall(r"Paper\s+([A-Za-z]{2}[A-Za-z0-9.]+)", html)
print(f"regex 'Paper X.Y' occurrences in raw HTML: {len(ids)}")
print(f"  first 5: {ids[:5]}")
print(f"  last 5:  {ids[-5:]}")

soup = BeautifulSoup(html, "html.parser")
tables = soup.find_all("table")
print(f"\n<table> elements on page: {len(tables)}")

# For each top-level container, count nested paper IDs
print("\nTop 10 <table> elements by paper-ID count:")
counts = []
for i, t in enumerate(tables):
    n = len(re.findall(r"Paper\s+[A-Za-z]{2}[A-Za-z0-9.]+", t.get_text(" ", strip=True)))
    counts.append((n, i))
counts.sort(reverse=True)
for n, i in counts[:10]:
    print(f"  table[{i}]: {n} paper IDs inside")

# Look at the FIRST paper to understand its container
print("\n--- searching for first paper container ---")
first_id = ids[0] if ids else None
if first_id:
    for tag_name in ("tr", "table", "div"):
        for el in soup.find_all(tag_name):
            txt = el.get_text(" ", strip=True)
            if f"Paper {first_id}" in txt and len(txt) < 5000:
                print(f"\n<{tag_name}> containing 'Paper {first_id}', length={len(txt)} chars")
                print(f"parent: <{el.parent.name if el.parent else '?'}>")
                # Dump a structural snippet
                snippet = str(el)[:2000]
                print("--- snippet ---")
                print(snippet)
                print("--- /snippet ---")
                break
        else:
            continue
        break
