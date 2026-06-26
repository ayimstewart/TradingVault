"""
quant_mind_fetcher.py — Daily quant research digest from arXiv.

Inspired by QuantMind (references/quant-mind) but runs standalone without
requiring the QuantMind package. Fetches recent finance/crypto/trading
papers from arXiv, formats them as a markdown digest, saves to sources/,
and auto-imports to NotebookLM notebook Green Bread Coach(GBC).

Designed to run as part of the morning brief (before signal generation)
so the research layer is grounded before NotebookLM queries.

Usage:
    python3 quant_mind_fetcher.py                  # fetch today's digest
    python3 quant_mind_fetcher.py --days 7         # last 7 days of papers
    python3 quant_mind_fetcher.py --max 20         # cap at 20 papers
    python3 quant_mind_fetcher.py --no-import      # skip NotebookLM import
    python3 quant_mind_fetcher.py --dry-run        # print digest, don't save
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

VAULT_ROOT   = Path(__file__).parent.parent
SOURCES_DIR  = VAULT_ROOT / "sources"
SOURCES_DIR.mkdir(exist_ok=True)

ARXIV_API = "https://export.arxiv.org/api/query"

# Target q-fin categories for precision — no noise from physics/robotics papers
# q-fin.TR = Trading/Microstructure, q-fin.CP = Computational Finance,
# q-fin.ST = Statistical Finance, q-fin.PM = Portfolio Mgmt, q-fin.RM = Risk
SEARCH_QUERIES = [
    "cat:q-fin.TR AND all:cryptocurrency",
    "cat:q-fin.TR AND all:momentum",
    "cat:q-fin.CP AND all:deep learning",
    "cat:q-fin.ST AND all:bitcoin",
    "cat:q-fin.RM AND all:drawdown",
    "cat:q-fin.PM AND all:crypto",
]

MAX_RESULTS_PER_QUERY = 5
NS = {"atom": "http://www.w3.org/2005/Atom"}


# ── Data types ────────────────────────────────────────────────────────────────

@dataclass
class Paper:
    arxiv_id: str
    title: str
    authors: list[str]
    abstract: str
    published: str
    url: str
    categories: list[str]

    def relevance_tags(self) -> list[str]:
        """Extract vault-relevant tags from abstract and title."""
        text = (self.title + " " + self.abstract).lower()
        tags: list[str] = []
        tag_map = {
            "BTC/crypto": ["bitcoin", "ethereum", "cryptocurrency", "crypto", "defi"],
            "Momentum/trend": ["momentum", "trend", "moving average", "ema", "mean reversion"],
            "ML/prediction": ["neural", "lstm", "transformer", "prediction", "forecasting", "deep learning"],
            "Risk mgmt": ["drawdown", "risk", "volatility", "var", "position sizing"],
            "Harmonic": ["harmonic", "fibonacci", "pattern", "gartley", "technical analysis"],
            "Macro": ["central bank", "interest rate", "fed", "macro", "inflation"],
        }
        for tag, keywords in tag_map.items():
            if any(kw in text for kw in keywords):
                tags.append(tag)
        return tags or ["General quant"]


# ── arXiv fetch ───────────────────────────────────────────────────────────────

def _fetch_arxiv(query: str, max_results: int = MAX_RESULTS_PER_QUERY) -> list[Paper]:
    """Query arXiv API and return structured Paper list."""
    # Pass query raw — category searches use cat: prefix, not all:
    params = {
        "search_query": query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }

    try:
        resp = requests.get(ARXIV_API, params=params, timeout=30)
        resp.raise_for_status()
        xml_data = resp.text
    except Exception as exc:
        print(f"  [arXiv] Fetch failed for '{query}': {exc}")
        return []

    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError as exc:
        print(f"  [arXiv] XML parse error: {exc}")
        return []

    papers: list[Paper] = []
    for entry in root.findall("atom:entry", NS):
        def _text(tag: str) -> str:
            el = entry.find(f"atom:{tag}", NS)
            return el.text.strip() if el is not None and el.text else ""

        arxiv_id = _text("id").split("/abs/")[-1]
        title    = re.sub(r"\s+", " ", _text("title"))
        abstract = re.sub(r"\s+", " ", _text("summary"))[:600]
        published = _text("published")[:10]

        authors = [
            a.find("atom:name", NS).text.strip()
            for a in entry.findall("atom:author", NS)
            if a.find("atom:name", NS) is not None
        ]

        categories = [
            c.get("term", "")
            for c in entry.findall("atom:category", NS)
        ]

        link_el = entry.find("atom:link[@rel='alternate']", NS)
        paper_url = link_el.get("href", "") if link_el is not None else _text("id")

        papers.append(Paper(
            arxiv_id=arxiv_id,
            title=title,
            authors=authors[:3],
            abstract=abstract,
            published=published,
            url=paper_url,
            categories=categories,
        ))

    return papers


def fetch_all_papers(
    days: int = 3,
    max_per_query: int = MAX_RESULTS_PER_QUERY,
) -> list[Paper]:
    """Fetch papers from all search queries, deduplicate, filter by date."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    seen: set[str] = set()
    all_papers: list[Paper] = []

    print(f"\n[quant_mind] Fetching research from arXiv (last {days} days)...")
    for query in SEARCH_QUERIES:
        print(f"  Query: {query!r}")
        papers = _fetch_arxiv(query, max_results=max_per_query)
        for paper in papers:
            if paper.arxiv_id in seen:
                continue
            if paper.published < cutoff:
                continue
            seen.add(paper.arxiv_id)
            all_papers.append(paper)

    all_papers.sort(key=lambda p: p.published, reverse=True)
    print(f"  → {len(all_papers)} unique papers found (≥{cutoff})")
    return all_papers


# ── Markdown formatter ────────────────────────────────────────────────────────

def format_digest(papers: list[Paper], days: int) -> str:
    """Render the paper list as a markdown digest for NotebookLM import."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [
        f"# Quant Research Digest — {today}",
        "",
        f"> Auto-generated by quant_mind_fetcher.py | Source: arXiv | Last {days} days",
        f"> Relevant to: BTC, ETH, SOL, XRP, LINK, PEPE | Strategy: TCL + Harmonic",
        "",
        f"**{len(papers)} papers found**",
        "",
    ]

    if not papers:
        lines += [
            "No recent papers matched the search queries for this period.",
            "Try increasing --days or check arXiv connectivity.",
        ]
        return "\n".join(lines)

    for i, paper in enumerate(papers, 1):
        tags = " | ".join(f"`{t}`" for t in paper.relevance_tags())
        authors_str = ", ".join(paper.authors) + (" et al." if len(paper.authors) >= 3 else "")

        lines += [
            f"## {i}. {paper.title}",
            "",
            f"**Authors:** {authors_str}  ",
            f"**Published:** {paper.published}  ",
            f"**Tags:** {tags}  ",
            f"**arXiv:** {paper.url}",
            "",
            f"**Abstract (excerpt):**",
            f"> {paper.abstract}{'...' if len(paper.abstract) == 600 else ''}",
            "",
            "---",
            "",
        ]

    lines += [
        "## Search Queries Used",
        "",
    ]
    for q in SEARCH_QUERIES:
        lines.append(f"- {q}")

    lines += [
        "",
        f"*Generated: {datetime.now(timezone.utc).isoformat()}*",
    ]

    return "\n".join(lines)


# ── Save + import ─────────────────────────────────────────────────────────────

def save_digest(content: str) -> Path:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path  = SOURCES_DIR / f"{today}-quant-research.md"
    path.write_text(content, encoding="utf-8")
    print(f"  ✓ Saved → {path}")
    return path


def import_to_notebooklm(path: Path) -> bool:
    """Add the digest to NotebookLM Green Bread Coach(GBC) via notebooklm_bridge."""
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from notebooklm_bridge import source_add, source_wait, NOTEBOOK, NOTEBOOK_ID

        print(f"\n[quant_mind] Importing to NotebookLM: '{NOTEBOOK}'")
        r = source_add(path, notebook=NOTEBOOK, notebook_id=NOTEBOOK_ID)
        if r.ok:
            print(f"  ✓ Source added to '{NOTEBOOK}'")
            print(f"  → Waiting for processing...")
            rw = source_wait(notebook=NOTEBOOK)
            if rw.ok:
                print(f"  ✓ Source grounded — notebook ready to query")
            else:
                print(f"  ⚠ source_wait: {rw.error} (may still work)")
            return True
        else:
            print(f"  ✗ source_add failed: {r.error}")
            print(f"  Manual fallback:")
            print(f"    notebooklm source add {path}")
            return False

    except ImportError:
        print("  ⚠ notebooklm_bridge not found — skipping auto-import")
        print(f"  Manual: notebooklm source add {path}")
        return False


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch daily quant research from arXiv and import to NotebookLM"
    )
    parser.add_argument("--days",      type=int, default=3,
                        help="Look back N days (default: 3)")
    parser.add_argument("--max",       type=int, default=MAX_RESULTS_PER_QUERY,
                        help="Max papers per search query (default: 5)")
    parser.add_argument("--no-import", action="store_true",
                        help="Skip NotebookLM import (save file only)")
    parser.add_argument("--dry-run",   action="store_true",
                        help="Print digest only — do not save or import")
    args = parser.parse_args()

    papers  = fetch_all_papers(days=args.days, max_per_query=args.max)
    digest  = format_digest(papers, days=args.days)

    if args.dry_run:
        print("\n" + "═" * 60)
        print(digest[:3000])
        if len(digest) > 3000:
            print(f"\n... [{len(digest)-3000} more chars] ...")
        print("═" * 60)
        print("\n[dry-run] Digest not saved.")
        return

    path = save_digest(digest)

    if not args.no_import:
        import_to_notebooklm(path)
    else:
        print(f"  [--no-import] Skipping NotebookLM. File saved at: {path}")

    print(f"\n[quant_mind] Done. {len(papers)} papers → {path.name}")
    print("  Run before morning_brief_auto.py to pre-ground the notebook.\n")


if __name__ == "__main__":
    main()
