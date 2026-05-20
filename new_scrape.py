#!/usr/bin/env python3
"""
Scrape ICRA 2026 papers (Tuesday, Wednesday, Thursday) and filter for ones
relevant to the IEEE RAS Technical Committee on Algorithms for Planning and
Control of Robot Motion.

TC scope (from ieee-ras.org):
    Motion planning and control, planning under sensing/uncertainty,
    feedback-based motion strategies, motion under kinematic / dynamic /
    nonholonomic constraints, planning in dynamic environments, hybrid
    systems, complexity of planning algorithms, novel applications.

Strategy:
    Each paper on the program pages has a structured "Keywords:" field
    using the official ICRA keyword taxonomy. We filter on those keywords
    (high precision) and fall back to abstract-text matching for a small
    set of strong phrases (catches papers tagged only with application
    keywords like Aerial Systems).

Output:
    icra26_tc_motion_papers.csv   -- all matched papers, one row each
    icra26_tc_motion_papers.md    -- same content, human-readable

Run:
    pip install requests beautifulsoup4
    python scrape_icra26_tc_motion.py
"""

import csv
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE = "https://ras.papercept.net/conferences/conferences/ICRA26/program"

# Day 3 = Tue, Day 4 = Wed, Day 5 = Thu
DAYS = {
    3: "Tuesday",
    4: "Wednesday",
    5: "Thursday",
}

# ICRA keywords (as they appear in the program) that map onto the TC scope.
# Lowercased for matching. Curated to be precise — only keywords that
# unambiguously fall under "algorithms for planning and control of robot
# motion". Borderline keywords (e.g. "Reinforcement Learning" alone) are
# excluded to avoid drowning the result in generic ML papers.
TC_KEYWORDS = {
    # Planning
    "motion and path planning",
    "constrained motion planning",
    "nonholonomic motion planning",
    "manipulation planning",
    "task and motion planning",
    "integrated planning and learning",
    "integrated planning and control",
    "planning under uncertainty",
    "planning, scheduling and coordination",
    "reactive and sensor-based planning",
    "kinodynamic planning",
    "path planning for multiple mobile robots or agents",
    "multi-robot path planning",
    "motion planning",
    # Control directly tied to motion
    "optimization and optimal control",
    "motion control",
    "whole-body motion planning and control",
    "compliance and impedance control",
    "robust/adaptive control",
    "underactuated robots",
    "nonholonomic mechanisms and systems",
    "collision avoidance",
    "human-aware motion planning",
    "formal methods in robotics and automation",
    # Hybrid / safety
    "hybrid logical/dynamical planning and verification",
    "robot safety",
}

# Strong abstract-text phrases. Only used if a paper has NO matching keyword.
# Kept tight to avoid false positives.
TC_ABSTRACT_PHRASES = [
    "motion planning",
    "trajectory optimization",
    "trajectory planning",
    "path planning",
    "model predictive control",
    "control barrier function",
    "sampling-based planning",
    "kinodynamic",
    "nonholonomic",
    "task and motion planning",
    "rrt*",
    " rrt ",
    "prm ",
    "hamilton-jacobi reachability",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}

OUT_DIR = Path(__file__).resolve().parent
CSV_PATH = OUT_DIR / "icra26_tc_motion_papers.csv"
MD_PATH = OUT_DIR / "icra26_tc_motion_papers.md"
SESSIONS_CSV_PATH = OUT_DIR / "icra26_sessions_halls.csv"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Paper:
    day: str
    paper_id: str          # e.g. "TuI1I.15"
    session: str           # e.g. "TuI1I"
    session_type: str = ""  # e.g. "Interactive Session", "Regular Session"
    hall: str = ""          # e.g. "Hall C", "Strauss 1-2"
    time_slot: str = ""    # e.g. "09:00-10:30"
    title: str = ""
    authors: list = field(default_factory=list)   # list of (name, affiliation)
    keywords: list = field(default_factory=list)
    abstract: str = ""
    matched_keywords: list = field(default_factory=list)
    matched_phrases: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch_day(day_num: int) -> str:
    url = f"{BASE}/ICRA26_ContentListWeb_{day_num}.html"
    print(f"  GET {url}")
    r = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    return r.text


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------

# Each paper is rendered as a <table> block. Inside it:
#   - a row with the paper ID (e.g. "09:00-10:30, Paper TuI1I.15")
#   - a row with the title (link with "Click to show or hide" tooltip)
#   - rows with author name + affiliation
#   - a row containing "Keywords:" and "Abstract:" text
#
# The reliable anchor is the "Paper " ID. We walk every table and pick out
# the ones that contain a paper ID row.

PAPER_ID_RE = re.compile(r"Paper\s+([A-Z][a-z][A-Za-z0-9]+\.\d+)")
TIME_RE = re.compile(r"(\d{2}:\d{2}-\d{2}:\d{2})")

# Session-header row example (rendered text):
#   "TuI1I Interactive Session, Hall C"
#   "TuI1K Keynote Session, Strauss 1-2"
#   "TuI1P Keynote Session, Hall A1 (Plenary)"
#   "TuAT1 Regular Session, Hall A1"
# Pattern: <session_code> <space> <session_type ending in "Session">,
# <hall>. Session codes are 2-letter day prefix + letters/digits, 4-7 chars
# total. Hall ends before any trailing "Add to My Program" or table cell.
SESSION_HEADER_RE = re.compile(
    r"\b([A-Z][a-z][A-Za-z0-9]{2,6})\s+"
    r"([A-Z][A-Za-z\- ]*?Session),\s+"
    r"([^|\n]+?)(?:\s+Add to My Program|\s*\||$)",
)


def parse_session_headers(soup) -> dict[str, tuple[str, str]]:
    """
    Return a dict mapping session_id -> (session_type, hall).

    Session headers are <tr> rows containing bold text like
    "TuI1I Interactive Session, Hall C". We scan all <tr> rows
    looking for that pattern.
    """
    sessions: dict[str, tuple[str, str]] = {}
    for tr in soup.find_all("tr"):
        text = tr.get_text(" ", strip=True)
        if "Session" not in text or "," not in text:
            continue
        # Skip if this row already looks like a paper header
        if "Paper " in text and re.search(r"\d{2}:\d{2}", text):
            continue
        m = SESSION_HEADER_RE.search(text)
        if not m:
            continue
        session_id, session_type, hall = m.group(1), m.group(2), m.group(3)
        # Clean up hall: drop trailing "Add to My Program" remnants and
        # collapse whitespace.
        hall = re.sub(r"\s+Add to My Program.*$", "", hall).strip()
        hall = re.sub(r"\s+", " ", hall)
        # First write wins (header rows appear once per session)
        if session_id not in sessions:
            sessions[session_id] = (session_type.strip(), hall)
    return sessions


def parse_day(html: str, day_label: str) -> tuple[list[Paper], dict[str, tuple[str, str]]]:
    """
    Each paper on a program page is rendered as a header row
    (<tr class="pHdr">) followed by sibling <tr> elements containing the
    title, authors, and a final cell with keywords + abstract. The next
    paper begins at the next pHdr (or the table ends).
    """
    soup = BeautifulSoup(html, "html.parser")
    sessions = parse_session_headers(soup)
    papers: list[Paper] = []

    for hdr in soup.find_all("tr", class_="pHdr"):
        hdr_text = hdr.get_text(" ", strip=True)
        m = PAPER_ID_RE.search(hdr_text)
        if not m:
            continue
        paper_id = m.group(1)
        session_id = paper_id.split(".", 1)[0]

        tm = TIME_RE.search(hdr_text)
        time_slot = tm.group(1) if tm else ""

        # Collect sibling <tr> rows until the next paper header (or end).
        body_rows = []
        for sib in hdr.find_next_siblings("tr"):
            classes = sib.get("class") or []
            if "pHdr" in classes:
                break
            body_rows.append(sib)

        # Title: first <a> in the body whose title attr is the show/hide hint.
        title = ""
        for tr in body_rows:
            for a in tr.find_all("a"):
                if a.get("title", "").startswith("Click to show or hide"):
                    title = a.get_text(" ", strip=True)
                    break
            if title:
                break
        if not title:
            # Fallback: first <a> we can find in the body rows
            for tr in body_rows:
                a = tr.find("a")
                if a and a.get_text(strip=True):
                    title = a.get_text(" ", strip=True)
                    break
        if not title:
            continue

        # Authors: rows of two <td>s where first <td> has an <a> to AuthorIndex.
        authors = []
        for tr in body_rows:
            tds = tr.find_all("td", recursive=False)
            if len(tds) != 2:
                continue
            a = tds[0].find("a")
            if not a or "AuthorIndex" not in a.get("href", ""):
                continue
            name = a.get_text(" ", strip=True)
            affil = tds[1].get_text(" ", strip=True)
            if name:
                authors.append((name, affil))

        # Keywords + abstract: usually packed into one cell at the bottom.
        # We assemble the body text and run the same regex split as before.
        body_text_parts = [tr.get_text(" ", strip=True) for tr in body_rows]
        body_text = "\n".join(body_text_parts)

        keywords = []
        # The keyword list is rendered as a sequence of <a> links inside one
        # cell, separated by ", ". Find that cell explicitly to get clean
        # individual keywords without falling back to text splitting.
        for tr in body_rows:
            cell_text = tr.get_text(" ", strip=True)
            if "Keywords:" not in cell_text:
                continue
            # Inside this row, keyword <a> links point at KeywordIndex.
            for a in tr.find_all("a"):
                if "KeywordIndex" in a.get("href", ""):
                    kw = a.get_text(" ", strip=True)
                    if kw:
                        keywords.append(kw)
            break

        # Abstract: text after "Abstract:" in the body text. Some papers
        # genuinely have no abstract field (e.g. the page I saw had one
        # such paper); leave it empty in that case.
        abstract = ""
        ab_block = re.search(r"Abstract:\s*(.*)", body_text, re.DOTALL)
        if ab_block:
            abstract = ab_block.group(1).strip()
            # Collapse internal whitespace
            abstract = re.sub(r"\s+", " ", abstract)

        session_type, hall = sessions.get(session_id, ("", ""))

        papers.append(
            Paper(
                day=day_label,
                paper_id=paper_id,
                session=session_id,
                session_type=session_type,
                hall=hall,
                time_slot=time_slot,
                title=title,
                authors=authors,
                keywords=keywords,
                abstract=abstract,
            )
        )

    return papers, sessions


# ---------------------------------------------------------------------------
# Filter
# ---------------------------------------------------------------------------

def matches_tc(paper: Paper) -> bool:
    paper.matched_keywords = []
    paper.matched_phrases = []

    kw_lower = [k.lower() for k in paper.keywords]
    for kw in kw_lower:
        if kw in TC_KEYWORDS:
            # Recover the original-case keyword for display
            for orig in paper.keywords:
                if orig.lower() == kw:
                    paper.matched_keywords.append(orig)
                    break

    if paper.matched_keywords:
        return True

    # No keyword match: try abstract phrases as a fallback
    ab = paper.abstract.lower()
    for phrase in TC_ABSTRACT_PHRASES:
        if phrase in ab:
            paper.matched_phrases.append(phrase.strip())

    return bool(paper.matched_phrases)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_csv(papers: list[Paper], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "day", "session", "session_type", "hall",
            "paper_id", "time_slot", "title",
            "authors", "affiliations", "icra_keywords",
            "matched_tc_keywords", "matched_abstract_phrases", "abstract",
        ])
        for p in papers:
            w.writerow([
                p.day, p.session, p.session_type, p.hall,
                p.paper_id, p.time_slot, p.title,
                "; ".join(n for n, _ in p.authors),
                "; ".join(a for _, a in p.authors),
                "; ".join(p.keywords),
                "; ".join(p.matched_keywords),
                "; ".join(p.matched_phrases),
                p.abstract,
            ])


def write_sessions_csv(
    sessions_by_day: dict[str, dict[str, tuple[str, str]]],
    path: Path,
) -> None:
    """Dump the session->(type, hall) lookup table to CSV."""
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["day", "session", "session_type", "hall"])
        for day in ("Tuesday", "Wednesday", "Thursday"):
            for sid in sorted(sessions_by_day.get(day, {})):
                stype, hall = sessions_by_day[day][sid]
                w.writerow([day, sid, stype, hall])


def write_markdown(papers: list[Paper], path: Path) -> None:
    by_day: dict[str, list[Paper]] = {}
    for p in papers:
        by_day.setdefault(p.day, []).append(p)

    with path.open("w", encoding="utf-8") as f:
        f.write("# ICRA 2026 — Papers relevant to TC on Algorithms for "
                "Planning and Control of Robot Motion\n\n")
        f.write(f"Total matched: **{len(papers)}**\n\n")
        for day in ("Tuesday", "Wednesday", "Thursday"):
            day_papers = by_day.get(day, [])
            f.write(f"## {day} ({len(day_papers)} papers)\n\n")
            for p in day_papers:
                f.write(f"### {p.paper_id} — {p.title}\n\n")
                location = p.hall or "(hall TBD)"
                f.write(f"- **Session/time/location:** {p.session} "
                        f"({p.session_type}) — {p.time_slot} — {location}\n")
                if p.authors:
                    f.write("- **Authors:** "
                            + "; ".join(f"{n} ({a})" for n, a in p.authors)
                            + "\n")
                if p.keywords:
                    f.write("- **ICRA keywords:** "
                            + ", ".join(p.keywords) + "\n")
                if p.matched_keywords:
                    f.write("- **Matched TC keywords:** "
                            + ", ".join(p.matched_keywords) + "\n")
                if p.matched_phrases:
                    f.write("- **Matched on abstract phrases:** "
                            + ", ".join(p.matched_phrases) + "\n")
                if p.abstract:
                    f.write(f"\n{p.abstract}\n")
                f.write("\n---\n\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    all_papers: list[Paper] = []
    sessions_by_day: dict[str, dict[str, tuple[str, str]]] = {}
    for day_num, day_label in DAYS.items():
        print(f"\n=== {day_label} (day {day_num}) ===")
        try:
            html = fetch_day(day_num)
        except requests.RequestException as e:
            print(f"  ! fetch failed: {e}", file=sys.stderr)
            return 1
        papers, sessions = parse_day(html, day_label)
        print(f"  parsed {len(papers)} papers across {len(sessions)} sessions")
        all_papers.extend(papers)
        sessions_by_day[day_label] = sessions
        time.sleep(1.0)  # be polite

    print(f"\nTotal parsed: {len(all_papers)}")

    matched = [p for p in all_papers if matches_tc(p)]
    print(f"Matched (TC-relevant): {len(matched)}")

    # Sort: day order, then session, then paper id
    day_order = {"Tuesday": 0, "Wednesday": 1, "Thursday": 2}
    matched.sort(key=lambda p: (day_order.get(p.day, 99), p.session, p.paper_id))

    write_csv(matched, CSV_PATH)
    write_markdown(matched, MD_PATH)
    write_sessions_csv(sessions_by_day, SESSIONS_CSV_PATH)
    print(f"\nWrote {CSV_PATH}")
    print(f"Wrote {MD_PATH}")
    print(f"Wrote {SESSIONS_CSV_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())