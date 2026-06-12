"""
research_tools.py — Academic and web research tools for the openclaw pipeline.

Priority order:
  1. ArXiv          — preprint papers (CS, physics, math, bio, econ, etc.)
  2. Semantic Scholar — peer-reviewed papers + citation counts
  3. PubMed          — biomedical / life sciences
  4. Wikipedia       — background context and definitions
  5. DuckDuckGo      — general web search (fill in the cracks)
  6. URL scraper     — follow any URL and extract full text

All functions return clean, structured plain text ready to inject into a prompt.
No API keys required for any of these.
"""

import re
import time
import logging
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus, urljoin
from typing import Optional

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "openclaw-research-agent/1.0 "
        "(academic research pipeline; contact: research@openclaw.local)"
    )
}
DEFAULT_TIMEOUT = 15
SCRAPE_TIMEOUT  = 20

# ─────────────────────────────────────────────────────────────────────────────
# 1. ArXiv
# ─────────────────────────────────────────────────────────────────────────────
ARXIV_API = "http://export.arxiv.org/api/query"
ARXIV_NS  = "http://www.w3.org/2005/Atom"

def arxiv_search(query: str, max_results: int = 8) -> str:
    """
    Search ArXiv for papers matching query.
    Returns formatted list of papers with title, authors, date, abstract.
    """
    log.info("ArXiv search: %s", query[:60])
    try:
        resp = requests.get(
            ARXIV_API,
            params={
                "search_query": f"all:{query}",
                "start":        0,
                "max_results":  max_results,
                "sortBy":       "relevance",
                "sortOrder":    "descending",
            },
            headers=HEADERS,
            timeout=DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()

        root    = ET.fromstring(resp.text)
        ns      = {"atom": ARXIV_NS}
        entries = root.findall("atom:entry", ns)

        if not entries:
            return f"ArXiv: no results for '{query}'"

        results = [f"=== ArXiv Search: '{query}' ({len(entries)} papers) ===\n"]
        for entry in entries:
            title    = _et_text(entry, "atom:title", ns).replace("\n", " ").strip()
            abstract = _et_text(entry, "atom:summary", ns).replace("\n", " ").strip()
            published = _et_text(entry, "atom:published", ns)[:10]
            authors  = [a.find("atom:name", ns).text for a in entry.findall("atom:author", ns)[:4]]
            arxiv_id = _et_text(entry, "atom:id", ns).split("/abs/")[-1]
            categories = [c.get("term", "") for c in entry.findall("atom:category", ns)[:3]]

            results.append(
                f"[{arxiv_id}] {title}\n"
                f"  Authors: {', '.join(authors)}\n"
                f"  Date: {published}  Categories: {', '.join(categories)}\n"
                f"  Abstract: {abstract[:500]}{'...' if len(abstract) > 500 else ''}\n"
                f"  URL: https://arxiv.org/abs/{arxiv_id}\n"
            )

        time.sleep(1)  # ArXiv rate limit courtesy
        return "\n".join(results)

    except Exception as e:
        log.error("ArXiv search failed: %s", e)
        return f"ArXiv search error: {e}"


def arxiv_fetch_paper(arxiv_id: str) -> str:
    """
    Fetch full abstract and metadata for a specific ArXiv paper by ID.
    Also attempts to fetch the HTML version for full text if available.
    """
    log.info("ArXiv fetch: %s", arxiv_id)
    try:
        # Clean ID
        arxiv_id = arxiv_id.strip().split("/")[-1]

        resp = requests.get(
            ARXIV_API,
            params={"id_list": arxiv_id, "max_results": 1},
            headers=HEADERS,
            timeout=DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()

        root  = ET.fromstring(resp.text)
        ns    = {"atom": ARXIV_NS}
        entry = root.find("atom:entry", ns)
        if entry is None:
            return f"ArXiv paper not found: {arxiv_id}"

        title    = _et_text(entry, "atom:title", ns).replace("\n", " ").strip()
        abstract = _et_text(entry, "atom:summary", ns).strip()
        published = _et_text(entry, "atom:published", ns)[:10]
        authors  = [a.find("atom:name", ns).text for a in entry.findall("atom:author", ns)]
        categories = [c.get("term", "") for c in entry.findall("atom:category", ns)]

        # Try HTML full text (ar5iv.org renders ArXiv papers as HTML)
        html_text = ""
        try:
            html_url = f"https://ar5iv.org/html/{arxiv_id}"
            html_resp = requests.get(html_url, headers=HEADERS, timeout=SCRAPE_TIMEOUT)
            if html_resp.status_code == 200:
                soup = BeautifulSoup(html_resp.content, "lxml")
                # Remove nav, references, figures
                for tag in soup.find_all(["nav", "figure", "script", "style"]):
                    tag.decompose()
                # Get sections
                sections = soup.find_all(["section", "article"])
                if sections:
                    full_text = "\n\n".join(
                        s.get_text(separator="\n", strip=True)[:2000]
                        for s in sections[:6]
                    )
                    html_text = f"\n\nFULL TEXT (first sections):\n{full_text}"
        except Exception:
            pass  # Full text is optional

        return (
            f"=== ArXiv Paper: {arxiv_id} ===\n"
            f"Title: {title}\n"
            f"Authors: {', '.join(authors)}\n"
            f"Published: {published}\n"
            f"Categories: {', '.join(categories)}\n"
            f"Abstract:\n{abstract}\n"
            f"URL: https://arxiv.org/abs/{arxiv_id}"
            f"{html_text}"
        )

    except Exception as e:
        log.error("ArXiv fetch failed: %s", e)
        return f"ArXiv fetch error: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Semantic Scholar
# ─────────────────────────────────────────────────────────────────────────────
SS_API = "https://api.semanticscholar.org/graph/v1"

def semantic_scholar_search(query: str, max_results: int = 6) -> str:
    """
    Search Semantic Scholar for peer-reviewed papers.
    Returns papers sorted by citation count (most cited first).
    """
    log.info("Semantic Scholar search: %s", query[:60])
    try:
        resp = requests.get(
            f"{SS_API}/paper/search",
            params={
                "query":  query,
                "limit":  max_results,
                "fields": "title,abstract,authors,year,citationCount,url,externalIds,tldr",
            },
            headers=HEADERS,
            timeout=DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()
        data   = resp.json()
        papers = data.get("data", [])

        if not papers:
            return f"Semantic Scholar: no results for '{query}'"

        # Sort by citation count descending
        papers.sort(key=lambda p: p.get("citationCount") or 0, reverse=True)

        results = [f"=== Semantic Scholar: '{query}' ({len(papers)} papers) ===\n"]
        for p in papers:
            title    = p.get("title", "Untitled")
            year     = p.get("year", "?")
            cites    = p.get("citationCount", 0)
            authors  = [a["name"] for a in (p.get("authors") or [])[:3]]
            abstract = (p.get("abstract") or "No abstract available.")[:500]
            tldr     = p.get("tldr", {})
            tldr_text = tldr.get("text", "") if tldr else ""
            url      = p.get("url", "")

            results.append(
                f"[{year}] {title}  (cited {cites}x)\n"
                f"  Authors: {', '.join(authors)}\n"
                + (f"  TL;DR: {tldr_text}\n" if tldr_text else "")
                + f"  Abstract: {abstract}{'...' if len(abstract) == 500 else ''}\n"
                f"  URL: {url}\n"
            )

        time.sleep(0.5)
        return "\n".join(results)

    except Exception as e:
        log.error("Semantic Scholar search failed: %s", e)
        return f"Semantic Scholar error: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# 3. PubMed
# ─────────────────────────────────────────────────────────────────────────────
PUBMED_SEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_FETCH  = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
PUBMED_SUMM   = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"

def pubmed_search(query: str, max_results: int = 5) -> str:
    """
    Search PubMed for biomedical/life-science literature.
    Best for: medicine, biology, neuroscience, pharmacology.
    """
    log.info("PubMed search: %s", query[:60])
    try:
        # Step 1: get IDs
        search_resp = requests.get(
            PUBMED_SEARCH,
            params={"db": "pubmed", "term": query, "retmax": max_results,
                    "retmode": "json", "sort": "relevance"},
            headers=HEADERS, timeout=DEFAULT_TIMEOUT,
        )
        search_resp.raise_for_status()
        ids = search_resp.json().get("esearchresult", {}).get("idlist", [])

        if not ids:
            return f"PubMed: no results for '{query}'"

        # Step 2: fetch summaries
        summ_resp = requests.get(
            PUBMED_SUMM,
            params={"db": "pubmed", "id": ",".join(ids), "retmode": "json"},
            headers=HEADERS, timeout=DEFAULT_TIMEOUT,
        )
        summ_resp.raise_for_status()
        uids = summ_resp.json().get("result", {})

        results = [f"=== PubMed: '{query}' ({len(ids)} papers) ===\n"]
        for uid in ids:
            paper = uids.get(uid, {})
            title   = paper.get("title", "Untitled")
            pubdate = paper.get("pubdate", "?")
            source  = paper.get("source", "")
            authors = [a["name"] for a in paper.get("authors", [])[:3]]
            results.append(
                f"[PMID:{uid}] {title}\n"
                f"  Journal: {source}  Published: {pubdate}\n"
                f"  Authors: {', '.join(authors)}\n"
                f"  URL: https://pubmed.ncbi.nlm.nih.gov/{uid}/\n"
            )

        time.sleep(0.5)
        return "\n".join(results)

    except Exception as e:
        log.error("PubMed search failed: %s", e)
        return f"PubMed error: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Wikipedia
# ─────────────────────────────────────────────────────────────────────────────
def wikipedia_search(topic: str) -> str:
    """
    Fetch a Wikipedia summary for background context on a topic.
    """
    log.info("Wikipedia: %s", topic[:60])
    try:
        # Try direct summary first
        slug = topic.strip().replace(" ", "_")
        resp = requests.get(
            f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote_plus(slug)}",
            headers=HEADERS, timeout=DEFAULT_TIMEOUT,
        )
        if resp.status_code == 200:
            data    = resp.json()
            title   = data.get("title", topic)
            extract = data.get("extract", "")
            url     = data.get("content_urls", {}).get("desktop", {}).get("page", "")
            return (
                f"=== Wikipedia: {title} ===\n"
                f"{extract[:2000]}{'...' if len(extract) > 2000 else ''}\n"
                f"URL: {url}"
            )

        # Fallback: search
        search_resp = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={"action": "opensearch", "search": topic, "limit": 3, "format": "json"},
            headers=HEADERS, timeout=DEFAULT_TIMEOUT,
        )
        results = search_resp.json()
        titles, _, urls = results[1], results[2], results[3]
        if titles:
            return wikipedia_search(titles[0])
        return f"Wikipedia: no article found for '{topic}'"

    except Exception as e:
        log.error("Wikipedia failed: %s", e)
        return f"Wikipedia error: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# 5. DuckDuckGo web search
# ─────────────────────────────────────────────────────────────────────────────
def web_search(query: str, max_results: int = 6) -> str:
    """
    Search the web via DuckDuckGo. No API key required.
    Returns titles, snippets, and URLs.
    """
    log.info("DuckDuckGo search: %s", query[:60])
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            raw = list(ddgs.text(query, max_results=max_results))

        if not raw:
            return f"Web search: no results for '{query}'"

        results = [f"=== Web Search: '{query}' ({len(raw)} results) ===\n"]
        for r in raw:
            results.append(
                f"{r.get('title', 'No title')}\n"
                f"  {r.get('body', '')[:300]}\n"
                f"  URL: {r.get('href', '')}\n"
            )
        return "\n".join(results)

    except ImportError:
        return "Web search unavailable (install duckduckgo-search)"
    except Exception as e:
        log.error("DuckDuckGo search failed: %s", e)
        return f"Web search error: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# 6. URL scraper
# ─────────────────────────────────────────────────────────────────────────────
SCRAPE_SKIP_TAGS = ["script", "style", "nav", "footer", "header",
                    "aside", "advertisement", "noscript", "iframe"]

def scrape_url(url: str, max_chars: int = 4000) -> str:
    """
    Scrape a URL and return clean extracted text.
    Removes navigation, scripts, ads. Extracts main content.
    """
    log.info("Scraping: %s", url[:80])
    try:
        resp = requests.get(
            url, headers=HEADERS, timeout=SCRAPE_TIMEOUT,
            allow_redirects=True,
        )
        resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")
        if "pdf" in content_type:
            return f"[PDF at {url} — use arxiv_fetch_paper for ArXiv PDFs]"

        soup = BeautifulSoup(resp.content, "lxml")

        # Remove noise
        for tag in soup.find_all(SCRAPE_SKIP_TAGS):
            tag.decompose()

        # Try to find main content area
        main = (
            soup.find("article")
            or soup.find("main")
            or soup.find(attrs={"role": "main"})
            or soup.find("div", class_=re.compile(r"content|article|post|body", re.I))
            or soup.body
        )

        if main:
            text = main.get_text(separator="\n", strip=True)
        else:
            text = soup.get_text(separator="\n", strip=True)

        # Clean up excessive blank lines
        text = re.sub(r"\n{3,}", "\n\n", text).strip()

        if len(text) > max_chars:
            text = text[:max_chars] + f"\n...(truncated at {max_chars} chars)"

        return f"=== Scraped: {url} ===\n{text}"

    except Exception as e:
        log.error("Scrape failed %s: %s", url, e)
        return f"Scrape error for {url}: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# 7. Composite: full research sweep on a topic
# ─────────────────────────────────────────────────────────────────────────────
def research_topic(topic: str, depth: str = "standard") -> str:
    """
    Run a full research sweep on a topic and return compiled findings.

    depth:
      "quick"    — ArXiv + Wikipedia only
      "standard" — ArXiv + Semantic Scholar + Wikipedia + web search
      "deep"     — all sources + scrape top URLs

    Returns a structured research brief ready to inject into a prompt.
    """
    log.info("Research sweep: topic='%s' depth=%s", topic[:60], depth)
    sections = []

    # ── Academic sources (primary) ─────────────────────────────────────────
    sections.append("## Academic Papers (ArXiv)")
    sections.append(arxiv_search(topic, max_results=6))
    time.sleep(1)

    if depth in ("standard", "deep"):
        sections.append("\n## Peer-Reviewed Papers (Semantic Scholar)")
        sections.append(semantic_scholar_search(topic, max_results=5))
        time.sleep(0.5)

        # Only hit PubMed for bio/medical topics
        bio_keywords = {"protein", "gene", "disease", "drug", "cell", "neural",
                        "brain", "clinical", "patient", "medical", "biological",
                        "cancer", "therapy", "molecular"}
        if any(kw in topic.lower() for kw in bio_keywords):
            sections.append("\n## Biomedical Literature (PubMed)")
            sections.append(pubmed_search(topic, max_results=4))
            time.sleep(0.5)

    # ── Background context ─────────────────────────────────────────────────
    sections.append("\n## Background (Wikipedia)")
    sections.append(wikipedia_search(topic))

    # ── Web search (secondary) ─────────────────────────────────────────────
    if depth in ("standard", "deep"):
        sections.append("\n## Web Search Results (DuckDuckGo)")
        sections.append(web_search(topic, max_results=5))

        # Also search for recent developments
        sections.append("\n## Recent Developments")
        sections.append(web_search(f"{topic} 2024 2025 latest research", max_results=4))

    # ── Deep: scrape top URLs ──────────────────────────────────────────────
    if depth == "deep":
        sections.append("\n## Scraped Sources")
        # Grab URLs from web search and scrape top 3
        try:
            from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                hits = list(ddgs.text(topic + " research overview", max_results=3))
            for hit in hits:
                url = hit.get("href", "")
                if url and "arxiv.org" not in url:  # arxiv already covered
                    sections.append(scrape_url(url, max_chars=2000))
                    time.sleep(1)
        except Exception as e:
            log.warning("Deep scrape failed: %s", e)

    return "\n\n".join(sections)


# ─────────────────────────────────────────────────────────────────────────────
# CrewAI tool wrappers
# ─────────────────────────────────────────────────────────────────────────────
def get_crewai_tools():
    """
    Return a list of CrewAI-compatible Tool objects for the Researcher agent.
    Safe to call even if crewai is not installed (returns empty list).
    """
    try:
        from crewai.tools import BaseTool
        from pydantic import BaseModel, Field

        class QueryInput(BaseModel):
            query: str = Field(description="Search query or topic")

        class UrlInput(BaseModel):
            url: str = Field(description="URL to scrape")

        class ArXivSearchTool(BaseTool):
            name: str = "ArXiv Academic Search"
            description: str = (
                "Search ArXiv preprint server for academic papers on any topic. "
                "Returns paper titles, authors, abstracts, and IDs. "
                "Best for: CS, AI/ML, physics, math, quantitative biology, economics."
            )
            args_schema: type[BaseModel] = QueryInput
            def _run(self, query: str) -> str:
                return arxiv_search(query, max_results=6)

        class ArXivFetchTool(BaseTool):
            name: str = "ArXiv Fetch Paper"
            description: str = (
                "Fetch the full abstract and text of a specific ArXiv paper by its ID "
                "(e.g. '2301.07041' or 'https://arxiv.org/abs/2301.07041'). "
                "Use after ArXiv Search to get full details on a promising paper."
            )
            args_schema: type[BaseModel] = QueryInput
            def _run(self, query: str) -> str:
                return arxiv_fetch_paper(query)

        class SemanticScholarTool(BaseTool):
            name: str = "Semantic Scholar Search"
            description: str = (
                "Search Semantic Scholar for peer-reviewed papers across all disciplines. "
                "Returns papers sorted by citation count — higher citations = more impactful. "
                "Includes TL;DR summaries when available."
            )
            args_schema: type[BaseModel] = QueryInput
            def _run(self, query: str) -> str:
                return semantic_scholar_search(query, max_results=6)

        class PubMedTool(BaseTool):
            name: str = "PubMed Biomedical Search"
            description: str = (
                "Search PubMed for biomedical and life science literature. "
                "Best for: medicine, biology, neuroscience, pharmacology, genetics."
            )
            args_schema: type[BaseModel] = QueryInput
            def _run(self, query: str) -> str:
                return pubmed_search(query, max_results=5)

        class WikipediaTool(BaseTool):
            name: str = "Wikipedia Background Search"
            description: str = (
                "Get a Wikipedia summary for background context on a topic, concept, or term. "
                "Good for establishing definitions and general overview before diving into papers."
            )
            args_schema: type[BaseModel] = QueryInput
            def _run(self, query: str) -> str:
                return wikipedia_search(query)

        class WebSearchTool(BaseTool):
            name: str = "DuckDuckGo Web Search"
            description: str = (
                "Search the web for recent articles, blog posts, news, and non-academic sources. "
                "Use as secondary source after exhausting academic databases. "
                "Good for very recent developments not yet in papers."
            )
            args_schema: type[BaseModel] = QueryInput
            def _run(self, query: str) -> str:
                return web_search(query, max_results=6)

        class ScrapeUrlTool(BaseTool):
            name: str = "Scrape Web Page"
            description: str = (
                "Fetch and extract the full text content from any URL. "
                "Use to read the full content of a specific page found via web search. "
                "Handles most websites; returns clean text without HTML noise."
            )
            args_schema: type[BaseModel] = UrlInput
            def _run(self, url: str) -> str:
                return scrape_url(url)

        return [
            ArXivSearchTool(),
            ArXivFetchTool(),
            SemanticScholarTool(),
            PubMedTool(),
            WikipediaTool(),
            WebSearchTool(),
            ScrapeUrlTool(),
        ]

    except ImportError:
        log.warning("crewai not available — returning empty tools list")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _et_text(element, path, ns) -> str:
    node = element.find(path, ns)
    return node.text if node is not None and node.text else ""
