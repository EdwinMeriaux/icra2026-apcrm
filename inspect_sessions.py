"""
Find how session headers (with the hall/room) are marked up.

Looking for blocks like:
    TuI1I  Interactive Session, Hall C
    TuAT1  Regular Session, Room 1
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
soup = BeautifulSoup(html, "html.parser")

# Sessions are referenced by id like TuI1I, TuAT1. Find a few sample
# session header lines.
sample_sessions = ["TuI1I", "TuAT1", "TuI1P", "TuI1K", "TuBT4"]

for sid in sample_sessions:
    print(f"\n=== Looking for session {sid} ===")
    # Find any element whose text contains the session code followed by
    # "Session"
    pattern = re.compile(rf"\b{sid}\b.{{0,100}}Session", re.DOTALL)
    found_one = False
    for node in soup.find_all(string=True):
        if pattern.search(str(node)) and len(str(node)) < 200:
            print(f"  string: {str(node).strip()[:200]!r}")
            el = node.parent
            for depth in range(6):
                if not el:
                    break
                classes = el.get('class', []) if hasattr(el, 'get') else []
                print(f"  depth {depth}: <{el.name}> class={classes} "
                      f"text_len={len(el.get_text(' ', strip=True))}")
                if depth == 2:
                    snippet = str(el)[:1500]
                    print(f"  --- HTML at depth 2 ---")
                    print(snippet)
                    print(f"  --- /HTML ---")
                el = el.parent
            found_one = True
            break
    if not found_one:
        print("  no match found")

# Also: list all <tr> classes used on the page, to find the session-header class.
print("\n=== Distinct <tr> classes on page ===")
classes_seen = {}
for tr in soup.find_all("tr"):
    cls = tuple(tr.get("class") or [])
    classes_seen[cls] = classes_seen.get(cls, 0) + 1
for cls, count in sorted(classes_seen.items(), key=lambda x: -x[1]):
    print(f"  {cls}: {count}")
