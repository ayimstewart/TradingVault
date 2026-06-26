"""
quant_mind_fetcher.py — Daily research digest: arXiv + web + social.

Pulls from multiple sources using agent-reach channels:
  - arXiv q-fin.* categories (academic papers — always on)
  - YouTube: yt-dlp search for trading videos (if installed)
  - Web:     Jina Reader for trading articles (free, no auth)
  - Reddit:  rdt-cli or OpenCLI (if configured and authenticated)
  - Twitter: twitter-cli (if configured and authenticated)

Saves to sources/YYYY-MM-DD-quant-research.md and auto-imports to
NotebookLM Green Bread Coach(GBC) for grounded morning brief queries.

Usage:
    python3 quant_mind_fetcher.py                  # all sources, today
    python3 quant_mind_fetcher.py --days 7         # look back 7 days
    python3 quant_mind_fetcher.py --no-web         # arXiv only
    python3 quant_mind_fetcher.py --no-import      # skip NotebookLM import
    python3 quant_mind_fetcher.py --dry-run        # print, don't save
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

def format_digest(papers: list[Paper], days: int, web_items: list[WebResult] | None = None) -> str:
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

    if web_items:
        lines.append(format_web_section(web_items))

    lines += [
        "",
        f"*Generated: {datetime.now(timezone.utc).isoformat()}*",
    ]

    return "\n".join(lines)


# ── Web / social fetch via agent-reach ───────────────────────────────────────

YOUTUBE_QUERIES = [
    "crypto trading EMA strategy 2026",
    "bitcoin technical analysis weekly",
    "LINK chainlink price analysis",
    "harmonic patterns crypto Gartley",
]

REDDIT_QUERIES = [
    "site:reddit.com/r/CryptoMarkets crypto trading strategy",
    "site:reddit.com/r/ethtrader ethereum technical analysis",
    "site:reddit.com/r/Chainlink LINK price",
]

TWITTER_QUERIES = [
    "crypto EMA trading strategy",
    "bitcoin weekly bias",
    "LINK Chainlink technical analysis",
]

JINA_READER = "https://r.jina.ai/"


@dataclass
class WebResult:
    source: str          # "youtube" | "reddit" | "twitter" | "web"
    title: str
    url: str
    snippet: str
    fetched_at: str


def _fetch_youtube(max_per_query: int = 3) -> list[WebResult]:
    """Search YouTube for trading content via yt-dlp."""
    import shutil
    import subprocess
    import json as _json

    if not shutil.which("yt-dlp"):
        print("  [youtube] yt-dlp not found — skipping")
        return []

    results: list[WebResult] = []
    seen: set[str] = set()

    for query in YOUTUBE_QUERIES[:2]:   # limit queries to keep runtime short
        cmd = [
            "yt-dlp",
            f"ytsearch{max_per_query}:{query}",
            "--dump-json", "--skip-download", "--no-playlist",
            "--quiet",
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            for line in proc.stdout.splitlines():
                try:
                    v = _json.loads(line)
                    vid_id = v.get("id", "")
                    if vid_id in seen:
                        continue
                    seen.add(vid_id)
                    desc = (v.get("description") or "")[:300].replace("\n", " ")
                    results.append(WebResult(
                        source="youtube",
                        title=v.get("title", "")[:120],
                        url=f"https://youtube.com/watch?v={vid_id}",
                        snippet=desc,
                        fetched_at=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    ))
                except (_json.JSONDecodeError, KeyError):
                    continue
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            print(f"  [youtube] Error for '{query}': {exc}")

    print(f"  [youtube] {len(results)} videos found")
    return results


def _fetch_jina_articles() -> list[WebResult]:
    """Fetch curated trading blog articles via Jina Reader."""
    # Jina Reader: GET r.jina.ai/<url> returns clean markdown text of any page
    URLS = [
        "https://www.tradingview.com/ideas/crypto/",
        "https://coincodex.com/crypto/chainlink/",
    ]
    results: list[WebResult] = []

    for url in URLS:
        try:
            resp = requests.get(f"{JINA_READER}{url}", timeout=20, headers={
                "Accept": "text/plain",
                "X-Return-Format": "markdown",
            })
            if resp.status_code == 200:
                text = resp.text[:800].replace("\n", " ").strip()
                results.append(WebResult(
                    source="web",
                    title=url.split("/")[2],
                    url=url,
                    snippet=text,
                    fetched_at=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                ))
        except Exception as exc:
            print(f"  [web] Jina fetch failed for {url}: {exc}")

    print(f"  [web] {len(results)} articles fetched via Jina Reader")
    return results


def _fetch_reddit() -> list[WebResult]:
    """Search Reddit via rdt-cli if authenticated, else skip."""
    import shutil
    import subprocess

    rdt = shutil.which("rdt")
    if not rdt:
        print("  [reddit] rdt-cli not installed — skipping (run: pipx install rdt-cli)")
        return []

    results: list[WebResult] = []
    for query in ["crypto trading EMA momentum", "LINK chainlink analysis"]:
        try:
            proc = subprocess.run(
                [rdt, "search", query, "--limit", "3", "--json"],
                capture_output=True, text=True, timeout=20,
            )
            if proc.returncode != 0:
                print(f"  [reddit] Auth required — run: rdt login")
                break
            import json as _json
            data = _json.loads(proc.stdout or "[]")
            for item in (data if isinstance(data, list) else []):
                results.append(WebResult(
                    source="reddit",
                    title=item.get("title", "")[:120],
                    url=item.get("url", ""),
                    snippet=(item.get("selftext") or item.get("body") or "")[:300],
                    fetched_at=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                ))
        except Exception as exc:
            print(f"  [reddit] Error: {exc}")
            break

    print(f"  [reddit] {len(results)} posts found")
    return results


def _fetch_twitter() -> list[WebResult]:
    """Search Twitter via twitter-cli if installed, else skip."""
    import shutil
    import subprocess

    tw = shutil.which("twitter")
    if not tw:
        print("  [twitter] twitter-cli not installed — skipping")
        print("  Install: pipx install twitter-cli  then  twitter login")
        return []

    results: list[WebResult] = []
    for query in ["crypto EMA trading", "$LINK technical analysis"]:
        try:
            proc = subprocess.run(
                [tw, "search", query, "--count", "3", "--json"],
                capture_output=True, text=True, timeout=20,
            )
            if proc.returncode != 0:
                print(f"  [twitter] Auth required — run: twitter login")
                break
            import json as _json
            tweets = _json.loads(proc.stdout or "[]")
            for t in (tweets if isinstance(tweets, list) else []):
                results.append(WebResult(
                    source="twitter",
                    title=f"@{t.get('username', 'unknown')}",
                    url=t.get("url", ""),
                    snippet=t.get("text", "")[:300],
                    fetched_at=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                ))
        except Exception as exc:
            print(f"  [twitter] Error: {exc}")
            break

    print(f"  [twitter] {len(results)} tweets found")
    return results


def fetch_web_content(skip_web: bool = False) -> list[WebResult]:
    """Fetch from all available web/social channels via agent-reach."""
    if skip_web:
        return []
    print(f"\n[quant_mind] Fetching web/social content via agent-reach...")
    results: list[WebResult] = []
    results.extend(_fetch_youtube())
    results.extend(_fetch_jina_articles())
    results.extend(_fetch_reddit())
    results.extend(_fetch_twitter())
    print(f"  → {len(results)} total web/social items")
    return results


def format_web_section(items: list[WebResult]) -> str:
    """Render web/social results as markdown section."""
    if not items:
        return ""

    lines = [
        "",
        "---",
        "",
        "## Web & Social Content",
        "",
        f"> Sources: {', '.join(sorted({i.source for i in items}))} | "
        f"via agent-reach channels",
        "",
    ]

    by_source: dict[str, list[WebResult]] = {}
    for item in items:
        by_source.setdefault(item.source, []).append(item)

    source_labels = {"youtube": "YouTube", "web": "Web Articles",
                     "reddit": "Reddit", "twitter": "Twitter/X"}

    for source, label in source_labels.items():
        group = by_source.get(source, [])
        if not group:
            continue
        lines += [f"### {label}", ""]
        for r in group:
            lines += [
                f"**{r.title}**  ",
                f"{r.url}  ",
                f"> {r.snippet}" if r.snippet else "",
                "",
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
    parser.add_argument("--no-web",    action="store_true",
                        help="Skip web/social fetch (arXiv only)")
    parser.add_argument("--dry-run",   action="store_true",
                        help="Print digest only — do not save or import")
    args = parser.parse_args()

    papers    = fetch_all_papers(days=args.days, max_per_query=args.max)
    web_items = fetch_web_content(skip_web=args.no_web)
    digest    = format_digest(papers, days=args.days, web_items=web_items)

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
