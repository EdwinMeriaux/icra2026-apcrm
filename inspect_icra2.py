"""
Second diagnostic: find the per-paper container.

Strategy: find the <td> or <tr> that contains the text "Paper TuI1I.1"
directly (not nested). Print its parent chain and a snippet.
"""

import re
import requests
from bs4 import BeautifulSoup, NavigableString

URL = "https://ras.papercept.net/conferences/conferences/ICRA26/program/ICRA26_ContentListWeb_3.html"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

html = requests.get(URL, headers=HEADERS, timeout=60).text
soup = BeautifulSoup(html, "html.parser")

# Find any element whose DIRECT text contains "Paper TuI1I.1" (so we
# don't keep climbing into ancestors).
target = "Paper TuI1I.1"
print(f"Looking for element directly containing: {target!r}\n")

# Walk all string nodes
for node in soup.find_all(string=True):
    if target in node and "TuI1I.10" not in node and "TuI1I.11" not in node:
        # Found the leaf string node. Walk up to show the structure.
        print("=== leaf string node ===")
        print(repr(node[:120]))
        el = node.parent
        depth = 0
        while el and depth < 8:
            attrs = dict(el.attrs) if hasattr(el, 'attrs') else {}
            text_len = len(el.get_text(" ", strip=True)) if hasattr(el, 'get_text') else 0
            print(f"  depth {depth}: <{el.name}> attrs={attrs} text_len={text_len}")
            depth += 1
            el = el.parent
        print()
        break

# Now: among all <tr> elements, count how many contain exactly one
# "Paper X.Y" match. Those are likely the per-paper rows.
print("\n=== Counting <tr> elements that look like paper rows ===")
single_paper_rows = 0
zero_paper_rows = 0
multi_paper_rows = 0
sample_single = None
for tr in soup.find_all("tr"):
    txt = tr.get_text(" ", strip=True)
    matches = re.findall(r"Paper\s+([A-Z][a-z][A-Za-z0-9]+\.\d+)", txt)
    if len(matches) == 1:
        single_paper_rows += 1
        if sample_single is None:
            sample_single = (tr, matches[0])
    elif len(matches) == 0:
        zero_paper_rows += 1
    else:
        multi_paper_rows += 1

print(f"  <tr> with exactly 1 paper ID: {single_paper_rows}")
print(f"  <tr> with 0 paper IDs: {zero_paper_rows}")
print(f"  <tr> with >1 paper IDs: {multi_paper_rows}")

if sample_single:
    tr, pid = sample_single
    print(f"\nSample <tr> containing Paper {pid}:")
    print(f"  text length: {len(tr.get_text(' ', strip=True))}")
    print(f"  parent: <{tr.parent.name if tr.parent else '?'}>")
    snippet = str(tr)
    if len(snippet) > 3000:
        snippet = snippet[:3000] + "\n... [truncated]"
    print("--- HTML ---")
    print(snippet)
    print("--- /HTML ---")
