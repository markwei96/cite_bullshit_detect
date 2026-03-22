import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

from config.settings import (
    SCRAPINGDOG_KEYS, SERPAPI_KEYS,
    MAX_DOWNLOAD_RETRIES, DOWNLOAD_TIMEOUT, PDF_DIR
)
from utils.logger import get_logger

logger = get_logger(__name__)

# Cache file for Scholar search results
SCHOLAR_CACHE_FILE = PDF_DIR / "scholar_cache.json"
ABSTRACT_CACHE_FILE = PDF_DIR / "abstracts.json"


@dataclass
class DownloadResult:
    cite_key: str
    found_on_scholar: bool
    pdf_path: Optional[Path]
    abstract: Optional[str]
    source: str  # "pdf_downloaded", "abstract_only", "not_found", "cached"
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Scholar search result cache
# ---------------------------------------------------------------------------

def _load_scholar_cache() -> dict:
    """Load cached Scholar search results from disk."""
    if SCHOLAR_CACHE_FILE.exists():
        try:
            return json.loads(SCHOLAR_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_scholar_cache(cache: dict):
    """Save Scholar search results to disk."""
    SCHOLAR_CACHE_FILE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def _load_abstract_cache() -> dict[str, str]:
    """Load cached abstracts from disk."""
    if ABSTRACT_CACHE_FILE.exists():
        try:
            return json.loads(ABSTRACT_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_abstract_cache(abstracts: dict[str, str]):
    """Save abstracts to disk."""
    if abstracts:
        ABSTRACT_CACHE_FILE.write_text(
            json.dumps(abstracts, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )


# ---------------------------------------------------------------------------
# Spider: Google Scholar API
# ---------------------------------------------------------------------------

class Spider:
    """Google Scholar search via ScrapingDog and SerpAPI.

    Adapted from ~/code/fake_citation_check_tool/spider.py
    """

    def __init__(self):
        self.api_keys = {
            "scrapingdog": SCRAPINGDOG_KEYS,
            "serpapi": SERPAPI_KEYS,
        }
        self.selected_key = {
            "provider": "None",
            "api_key": "None",
            "usage": 0,
            "limit": 0,
            "use_rate": 100,
        }
        self._init_api_key()

    def _init_api_key(self):
        """Check all API keys, print usage summary, select the best one."""
        api_usages = self._get_api_usage()
        if api_usages:
            logger.info("=" * 50)
            logger.info("API Usage Summary:")
            logger.info("=" * 50)
            for item in api_usages:
                remaining = item["limit"] - item["usage"]
                logger.info(
                    f"  {item['provider']:12s} ...{item['api_key'][-6:]}: "
                    f"{item['usage']}/{item['limit']} used "
                    f"({item['use_rate']:.1f}%), {remaining} remaining"
                )
            logger.info("=" * 50)
            self._select_best_key(api_usages)
        else:
            logger.warning("No valid API keys configured. Set SCRAPINGDOG_KEYS or SERPAPI_KEYS in .env")

    def _get_api_usage(self) -> list[dict]:
        """Query usage for all configured API keys."""
        base_urls = {
            "scrapingdog": "https://api.scrapingdog.com/account?api_key=",
            "serpapi": "https://serpapi.com/account?api_key=",
        }
        usages = []
        for provider, keys in self.api_keys.items():
            for key in keys:
                try:
                    resp = requests.get(base_urls[provider] + key, timeout=10)
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                    if provider == "scrapingdog":
                        usage = int(data["requestUsed"])
                        limit = int(data["requestLimit"])
                    else:  # serpapi
                        usage = int(data["this_month_usage"])
                        limit = int(data["searches_per_month"])
                    usages.append({
                        "provider": provider,
                        "api_key": key,
                        "usage": usage,
                        "limit": limit,
                        "use_rate": usage / limit * 100 if limit > 0 else 100,
                    })
                except Exception as e:
                    logger.warning(f"Failed to check {provider} key: {e}")
        return usages

    def _select_best_key(self, usages: list[dict] = None):
        """Select the API key with the lowest usage rate."""
        if usages is None:
            usages = self._get_api_usage()
        for item in usages:
            if item["usage"] >= item["limit"]:
                logger.warning(f"  {item['provider']} ...{item['api_key'][-6:]} has reached its limit. Skipping.")
                continue
            if self.selected_key["provider"] == "None" or item["use_rate"] < self.selected_key["use_rate"]:
                self.selected_key = item
        if self.selected_key["provider"] != "None":
            logger.info(f"Selected: {self.selected_key['provider']} ...{self.selected_key['api_key'][-6:]}")
        else:
            logger.error("All API keys exhausted!")

    def search(self, query: str) -> list[dict]:
        """Search Google Scholar for a paper title."""
        if self.selected_key["provider"] == "None":
            logger.error("No valid API key available")
            return []

        if self.selected_key["provider"] == "scrapingdog":
            return self._scrapingdog_search(query)
        else:
            return self._serpapi_search(query)

    def _scrapingdog_search(self, query: str) -> list[dict]:
        params = {
            "api_key": self.selected_key["api_key"],
            "query": query,
            "results": 5,
        }
        try:
            resp = requests.get(
                "https://api.scrapingdog.com/google_scholar",
                params=params, timeout=DOWNLOAD_TIMEOUT
            )
            if resp.status_code == 200:
                return resp.json().get("scholar_results", [])
            logger.warning(f"ScrapingDog search failed: HTTP {resp.status_code}")
        except Exception as e:
            logger.warning(f"ScrapingDog search error: {e}")
        return []

    def _serpapi_search(self, query: str) -> list[dict]:
        params = {
            "api_key": self.selected_key["api_key"],
            "q": query,
            "hl": "en",
            "engine": "google_scholar",
        }
        try:
            resp = requests.get(
                "https://serpapi.com/search",
                params=params, timeout=DOWNLOAD_TIMEOUT
            )
            if resp.status_code == 200:
                return resp.json().get("organic_results", [])
            logger.warning(f"SerpAPI search failed: HTTP {resp.status_code}")
        except Exception as e:
            logger.warning(f"SerpAPI search error: {e}")
        return []


# ---------------------------------------------------------------------------
# Search result matching & extraction helpers
# ---------------------------------------------------------------------------

def _match_title(search_results: list[dict], target_title: str) -> Optional[dict]:
    """Find a matching result by comparing titles (case-insensitive)."""
    target_clean = re.sub(r'\s+', ' ', target_title.lower().strip())
    for item in search_results:
        item_title = re.sub(r'\s+', ' ', item.get("title", "").lower().strip())
        # Exact match or high similarity (one contains the other)
        if item_title == target_clean:
            return item
        if len(target_clean) > 20 and (target_clean in item_title or item_title in target_clean):
            return item
    return None


def _extract_pdf_url(result: dict) -> Optional[str]:
    """Extract PDF URL from a Scholar search result."""
    # ScrapingDog format: resources.link
    resources = result.get("resources", {})
    if isinstance(resources, dict):
        link = resources.get("link")
        if link:
            return link
    elif isinstance(resources, list):
        for r in resources:
            if isinstance(r, dict) and r.get("link"):
                return r["link"]

    # SerpAPI format: resources[0].link or direct link
    resources_list = result.get("resources", [])
    if isinstance(resources_list, list):
        for r in resources_list:
            link = r.get("link", "")
            if link and (".pdf" in link.lower() or "pdf" in r.get("file_format", "").lower()):
                return link

    return None


def _extract_abstract(result: dict) -> Optional[str]:
    """Extract abstract/snippet from a Scholar search result."""
    return result.get("snippet") or result.get("description") or None


def _is_pdf_response(response: requests.Response) -> bool:
    """Check if a response contains a PDF."""
    content_type = response.headers.get("Content-Type", "").lower()
    return "application/pdf" in content_type


def _try_extract_pdf_from_page(url: str) -> Optional[str]:
    """Try to find a direct PDF link from an HTML page (publisher landing page)."""
    try:
        resp = requests.get(url, timeout=DOWNLOAD_TIMEOUT, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        if resp.status_code != 200:
            return None

        content_type = resp.headers.get("Content-Type", "").lower()
        if "application/pdf" in content_type:
            return url  # The URL itself serves PDF

        if "text/html" not in content_type:
            return None

        soup = BeautifulSoup(resp.text, "html.parser")

        # Check meta tags for PDF URL
        for meta in soup.find_all("meta", attrs={"name": "citation_pdf_url"}):
            pdf_url = meta.get("content")
            if pdf_url:
                return pdf_url

        # Check links with .pdf extension
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if href.lower().endswith(".pdf"):
                if not href.startswith("http"):
                    from urllib.parse import urljoin
                    href = urljoin(url, href)
                return href

    except Exception as e:
        logger.debug(f"Failed to extract PDF from page {url}: {e}")
    return None


def _download_pdf(url: str, save_path: Path) -> bool:
    """Download a PDF from URL. Returns True on success."""
    for attempt in range(MAX_DOWNLOAD_RETRIES):
        try:
            resp = requests.get(url, timeout=DOWNLOAD_TIMEOUT, stream=True, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            if resp.status_code != 200:
                continue

            # Check if it's actually a PDF
            if _is_pdf_response(resp):
                with open(save_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)
                return True

            # Not a PDF, try to find PDF link in the page
            pdf_url = _try_extract_pdf_from_page(url)
            if pdf_url and pdf_url != url:
                return _download_pdf(pdf_url, save_path)

            return False
        except Exception as e:
            logger.debug(f"Download attempt {attempt + 1} failed for {url}: {e}")
            time.sleep(2)
    return False


# ---------------------------------------------------------------------------
# Core: search + download with caching
# ---------------------------------------------------------------------------

def search_and_download(spider: Spider, bib_entry, pdf_dir: Path,
                        scholar_cache: dict, abstract_cache: dict) -> DownloadResult:
    """Search for a paper on Google Scholar and try to download its PDF.

    Uses scholar_cache to avoid redundant API calls.
    """
    key = bib_entry.key
    pdf_path = pdf_dir / f"{key}.pdf"

    # Skip if PDF already downloaded
    if pdf_path.exists() and pdf_path.stat().st_size > 0:
        abstract = abstract_cache.get(key)
        return DownloadResult(key, True, pdf_path, abstract, "cached")

    title = bib_entry.title
    if not title:
        return DownloadResult(key, False, None, None, "not_found", "No title in bib entry")

    # Check scholar cache first
    if key in scholar_cache:
        cached_entry = scholar_cache[key]
        matched = cached_entry.get("matched")
        if matched is None:
            # Previously searched but not found
            abstract = abstract_cache.get(key)
            if abstract:
                return DownloadResult(key, False, None, abstract, "abstract_only")
            return DownloadResult(key, False, None, None, "not_found", "Not found (cached)")
        # Have cached search result, try to download PDF
        abstract = _extract_abstract(matched) or abstract_cache.get(key)
        pdf_url = _extract_pdf_url(matched)
        if pdf_url:
            success = _download_pdf(pdf_url, pdf_path)
            if success:
                return DownloadResult(key, True, pdf_path, abstract, "pdf_downloaded")
            link = matched.get("link")
            if link and link != pdf_url:
                actual_pdf = _try_extract_pdf_from_page(link)
                if actual_pdf:
                    success = _download_pdf(actual_pdf, pdf_path)
                    if success:
                        return DownloadResult(key, True, pdf_path, abstract, "pdf_downloaded")
        if abstract:
            return DownloadResult(key, True, None, abstract, "abstract_only")
        return DownloadResult(key, True, None, None, "not_found", "Found but no PDF or abstract (cached)")

    # No cache — search via API
    results = spider.search(title)
    matched = _match_title(results, title)

    # Save to cache (even if not found, to avoid re-searching)
    scholar_cache[key] = {
        "title": title,
        "matched": matched,
    }

    if matched is None:
        return DownloadResult(key, False, None, None, "not_found", "Not found on Google Scholar")

    # Found on Scholar - try to get PDF
    abstract = _extract_abstract(matched)
    pdf_url = _extract_pdf_url(matched)

    if pdf_url:
        success = _download_pdf(pdf_url, pdf_path)
        if success:
            return DownloadResult(key, True, pdf_path, abstract, "pdf_downloaded")
        # PDF download failed, try extracting from the link
        link = matched.get("link")
        if link and link != pdf_url:
            actual_pdf = _try_extract_pdf_from_page(link)
            if actual_pdf:
                success = _download_pdf(actual_pdf, pdf_path)
                if success:
                    return DownloadResult(key, True, pdf_path, abstract, "pdf_downloaded")

    # No PDF available, fall back to abstract
    if abstract:
        return DownloadResult(key, True, None, abstract, "abstract_only")

    return DownloadResult(key, True, None, None, "not_found", "Found but no PDF or abstract")


def download_all(records: list, pdf_dir: Path) -> dict[str, DownloadResult]:
    """Download PDFs for all citation records."""
    spider = Spider()
    results = {}

    # Load caches
    scholar_cache = _load_scholar_cache()
    abstract_cache = _load_abstract_cache()

    cached_count = sum(1 for r in records if r.bib_entry.key in scholar_cache)
    if cached_count > 0:
        logger.info(f"Scholar cache: {cached_count}/{len(records)} papers already searched")

    for i, record in enumerate(records):
        key = record.bib_entry.key
        is_cached = key in scholar_cache or (pdf_dir / f"{key}.pdf").exists()
        logger.info(f"[{i + 1}/{len(records)}] {'(cached) ' if is_cached else ''}Searching: {record.bib_entry.title[:60]}...")

        result = search_and_download(spider, record.bib_entry, pdf_dir, scholar_cache, abstract_cache)

        # Update abstract cache
        if result.abstract:
            abstract_cache[key] = result.abstract

        results[key] = result

        status_icon = {"pdf_downloaded": "PDF", "abstract_only": "ABS", "cached": "CACHE", "not_found": "MISS"}
        logger.info(f"  [{status_icon.get(result.source, '?')}] {key}")

        # Rate limiting — only between actual API requests
        if not is_cached and result.source != "cached":
            time.sleep(2)

    # Save caches
    _save_scholar_cache(scholar_cache)
    _save_abstract_cache(abstract_cache)
    logger.info(f"Saved scholar cache ({len(scholar_cache)} entries) and abstracts ({len(abstract_cache)} entries)")

    # Summary
    stats = {}
    for r in results.values():
        stats[r.source] = stats.get(r.source, 0) + 1
    logger.info(f"Download summary: {stats}")

    return results
