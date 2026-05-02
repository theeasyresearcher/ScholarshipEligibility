#!/usr/bin/env python3
"""
scraper.py — Resilient Scholarship Data Scraper
================================================
Collects scholarship data from:
  1. Scholarise.in  (WordPress REST API + HTML fallback)
  2. Buddy4Study     (HTML scraping with anti-bot measures)
  3. National Scholarship Portal / govt portals (HTML scraping)

Merges, deduplicates, and writes to scholarships.json.

Usage:
    python scraper.py
    python scraper.py --debug      # verbose logging
"""

import json
import logging
import random
import re
import sys
import time
import hashlib
import argparse
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

# ── Optional Selenium import (graceful fallback) ──────────────────────────────
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

# ── Logging Setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("scraper.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
OUTPUT_FILE   = Path("scholarships.json")
REQUEST_TIMEOUT = 20   # seconds per request
MIN_DELAY     = 2.0    # seconds between requests (polite crawling)
MAX_DELAY     = 5.0

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",

    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",

    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",

    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
]

COMMON_HEADERS = {
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en-US;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection":      "keep-alive",
    "DNT":             "1",
}

# ── Schema ────────────────────────────────────────────────────────────────────
SCHEMA_DEFAULTS = {
    "id":             None,
    "name":           "Unknown Scholarship",
    "amount":         "Varies",
    "deadline":       "Varies",
    "eligibility":    "Check official portal for eligibility details.",
    "link":           "#",
    "type":           "central",          # central | state | private
    "categories":     ["General", "OBC", "SC", "ST", "EWS"],
    "gender":         "all",              # all | male | female | transgender
    "states":         ["All"],
    "qualifications": ["All"],
    "max_income":     None,
    "min_marks":      None,
    "min_age":        None,
    "max_age":        None,
    "disability_only": False,
    "source":         "unknown",
    "scraped_at":     None,
}

# ── Utilities ─────────────────────────────────────────────────────────────────

def get_session() -> requests.Session:
    """Create a requests session with randomised headers."""
    session = requests.Session()
    session.headers.update(COMMON_HEADERS)
    session.headers["User-Agent"] = random.choice(USER_AGENTS)
    return session


def polite_delay(min_s: float = MIN_DELAY, max_s: float = MAX_DELAY) -> None:
    delay = random.uniform(min_s, max_s)
    log.debug("Sleeping %.1fs", delay)
    time.sleep(delay)


def make_id(name: str, source: str) -> str:
    """Stable, URL-safe ID from name + source."""
    raw = f"{source}::{name}".lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", raw)[:60].strip("-")
    suffix = hashlib.md5(raw.encode()).hexdigest()[:6]
    return f"{slug}-{suffix}"


def normalise(entry: dict) -> dict:
    """Merge entry into the canonical schema."""
    result = dict(SCHEMA_DEFAULTS)
    result.update({k: v for k, v in entry.items() if v is not None})
    result["scraped_at"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    if not result["id"]:
        result["id"] = make_id(result["name"], result.get("source", "unknown"))
    return result


def safe_text(tag) -> str:
    """Extract clean text from a BS4 tag."""
    return tag.get_text(separator=" ", strip=True) if tag else ""


def extract_income(text: str) -> Optional[int]:
    """Extract numeric income limit from strings like 'below ₹2.5 lakh'."""
    text = text.lower()
    m = re.search(r"(\d+(?:\.\d+)?)\s*lakh", text)
    if m:
        return int(float(m.group(1)) * 100_000)
    m = re.search(r"(\d[\d,]+)", text)
    if m:
        return int(m.group(1).replace(",", ""))
    return None


def extract_marks(text: str) -> Optional[float]:
    """Extract minimum percentage from strings like 'min 60% marks'."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    return float(m.group(1)) if m else None


# ── Source 1: Scholarise.in ───────────────────────────────────────────────────

def scrape_scholarise(session: requests.Session) -> list[dict]:
    """
    Primary: WordPress REST API (/wp-json/wp/v2/posts)
    Fallback: HTML parsing of the homepage listing.
    """
    log.info("── Source 1: Scholarise.in ──────────────────────────")
    results = []

    # --- Try WP REST API first ---
    api_url = "https://scholarise.in/wp-json/wp/v2/posts"
    params  = {"per_page": 50, "status": "publish", "_fields": "id,title,excerpt,link,date,tags"}
    try:
        log.info("Trying WP REST API: %s", api_url)
        resp = session.get(api_url, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        posts = resp.json()
        log.info("WP API returned %d posts", len(posts))

        for post in posts:
            title   = BeautifulSoup(post.get("title", {}).get("rendered", ""), "html.parser").get_text()
            excerpt = BeautifulSoup(post.get("excerpt", {}).get("rendered", ""), "html.parser").get_text(strip=True)
            link    = post.get("link", "https://scholarise.in")

            entry = {
                "name":        title or "Scholarship from Scholarise",
                "eligibility": excerpt[:400] if excerpt else "See scholarship post for full details.",
                "link":        link,
                "type":        _guess_type(title + " " + excerpt),
                "categories":  _guess_categories(title + " " + excerpt),
                "max_income":  extract_income(excerpt),
                "min_marks":   extract_marks(excerpt),
                "source":      "scholarise.in",
            }
            results.append(normalise(entry))
            polite_delay(0.5, 1.5)

        log.info("Scholarise API: scraped %d scholarships", len(results))
        return results

    except Exception as e:
        log.warning("WP REST API failed (%s). Falling back to HTML scraping.", e)

    # --- HTML fallback ---
    polite_delay()
    try:
        log.info("Fetching HTML: https://scholarise.in/")
        resp = session.get("https://scholarise.in/", timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Common WordPress post selectors
        articles = (
            soup.select("article.post")
            or soup.select(".post-item")
            or soup.select(".entry-content")
            or soup.select("h2.entry-title")
        )
        log.info("HTML fallback: found %d article elements", len(articles))

        for art in articles[:30]:
            title_tag = art.select_one("h2, h3, .entry-title, .post-title")
            link_tag  = art.select_one("a")
            excerpt   = art.select_one(".entry-summary, .excerpt, p")

            title = safe_text(title_tag) or safe_text(link_tag) or "Scholarship"
            link  = link_tag["href"] if link_tag and link_tag.get("href") else "https://scholarise.in"
            desc  = safe_text(excerpt)

            if not title or title.lower() in ("read more", "continue reading", ""):
                continue

            entry = {
                "name":        title,
                "eligibility": desc[:400] if desc else "Visit Scholarise.in for eligibility details.",
                "link":        link if link.startswith("http") else "https://scholarise.in" + link,
                "type":        _guess_type(title + " " + desc),
                "categories":  _guess_categories(title + " " + desc),
                "max_income":  extract_income(desc),
                "min_marks":   extract_marks(desc),
                "source":      "scholarise.in",
            }
            results.append(normalise(entry))

        log.info("Scholarise HTML fallback: scraped %d scholarships", len(results))

    except Exception as e:
        log.error("Scholarise HTML scrape also failed: %s", e)

    return results


# ── Source 2: Buddy4Study ─────────────────────────────────────────────────────

def scrape_buddy4study(session: requests.Session) -> list[dict]:
    """
    Scrape scholarship listings from Buddy4Study.
    Uses randomised headers and delays to respect rate limits.
    Tries multiple listing pages.
    """
    log.info("── Source 2: Buddy4Study ────────────────────────────")
    results  = []
    base_url = "https://www.buddy4study.com"
    pages    = [
        "/scholarships",
        "/scholarships?type=central-government",
        "/scholarships?type=state-government",
    ]

    for page_path in pages:
        url = base_url + page_path
        polite_delay()
        session.headers["User-Agent"] = random.choice(USER_AGENTS)
        session.headers["Referer"] = base_url + "/"

        try:
            log.info("Fetching: %s", url)
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            # Buddy4Study card selectors (as of 2024–25 structure)
            cards = (
                soup.select(".scholarship-card")
                or soup.select(".b4s-scholarship-card")
                or soup.select("[class*='scholarship-item']")
                or soup.select("article")
            )
            log.info("  Found %d cards on %s", len(cards), page_path)

            for card in cards:
                title_el    = card.select_one("h2, h3, .scholarship-title, .card-title, [class*='title']")
                amount_el   = card.select_one(".amount, [class*='amount'], [class*='award']")
                deadline_el = card.select_one(".deadline, [class*='deadline'], [class*='last-date']")
                elig_el     = card.select_one(".eligibility, [class*='eligible'], p")
                link_el     = card.select_one("a[href]")

                title    = safe_text(title_el)
                if not title:
                    continue

                amount   = safe_text(amount_el) or "Varies"
                deadline = safe_text(deadline_el) or "Varies"
                elig     = safe_text(elig_el) or "Check Buddy4Study for eligibility."

                href = link_el["href"] if link_el else ""
                link = href if href.startswith("http") else base_url + href

                entry = {
                    "name":        title,
                    "amount":      _clean_amount(amount),
                    "deadline":    _parse_deadline(deadline),
                    "eligibility": elig[:400],
                    "link":        link or base_url,
                    "type":        _guess_type(title + " " + elig),
                    "categories":  _guess_categories(title + " " + elig),
                    "gender":      _guess_gender(title + " " + elig),
                    "max_income":  extract_income(elig),
                    "min_marks":   extract_marks(elig),
                    "disability_only": _is_disability(title + " " + elig),
                    "source":      "buddy4study.com",
                }
                results.append(normalise(entry))

        except requests.exceptions.Timeout:
            log.warning("Timeout on %s — skipping", url)
        except requests.exceptions.HTTPError as e:
            log.warning("HTTP error on %s: %s — skipping", url, e)
        except Exception as e:
            log.error("Unexpected error scraping %s: %s", url, e)

    log.info("Buddy4Study: scraped %d scholarships total", len(results))
    return results


# ── Source 3: National Scholarship Portal (NSP) ───────────────────────────────

def scrape_nsp(session: requests.Session) -> list[dict]:
    """
    Scrape the National Scholarship Portal (scholarships.gov.in).
    NSP has Cloudflare-like protection; we try the public services list.
    Falls back to a curated static list of well-known NSP schemes.
    """
    log.info("── Source 3: National Scholarship Portal (NSP) ──────")
    results = []

    nsp_urls = [
        "https://scholarships.gov.in/fresh/newstudentregistrations/getAllServices",
        "https://scholarships.gov.in/public/schemeData/currentSchemes",
        "https://scholarships.gov.in",
    ]

    session.headers["Referer"] = "https://scholarships.gov.in/"
    session.headers["User-Agent"] = random.choice(USER_AGENTS)

    for url in nsp_urls:
        polite_delay()
        try:
            log.info("Trying NSP URL: %s", url)
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()

            # Try JSON first
            if "json" in resp.headers.get("Content-Type", ""):
                data = resp.json()
                schemes = data if isinstance(data, list) else data.get("data", data.get("schemes", []))
                log.info("NSP JSON: found %d schemes", len(schemes))
                for s in schemes:
                    entry = _parse_nsp_json_scheme(s)
                    if entry:
                        results.append(normalise(entry))
                if results:
                    break

            # Try HTML
            soup = BeautifulSoup(resp.text, "html.parser")
            rows = (
                soup.select("table tr")
                or soup.select(".scheme-list li")
                or soup.select("[class*='scheme']")
            )
            log.info("NSP HTML: found %d rows", len(rows))
            for row in rows[1:]:  # skip header row
                cells = row.find_all(["td", "th"])
                if len(cells) >= 2:
                    title = safe_text(cells[0])
                    link_tag = row.find("a")
                    link = link_tag["href"] if link_tag else "https://scholarships.gov.in"
                    link = link if link.startswith("http") else "https://scholarships.gov.in" + link

                    if title:
                        results.append(normalise({
                            "name":   title,
                            "link":   link,
                            "type":   "central",
                            "source": "scholarships.gov.in",
                            "categories": _guess_categories(title),
                        }))
            if results:
                break

        except requests.exceptions.Timeout:
            log.warning("NSP timeout on %s — trying next URL", url)
        except requests.exceptions.HTTPError as e:
            log.warning("NSP HTTP error %s: %s", url, e)
        except Exception as e:
            log.error("NSP error on %s: %s", url, e)

    if not results:
        log.warning("All NSP live URLs failed. Using curated static NSP data.")
        results = _nsp_static_fallback()

    log.info("NSP: %d scholarships collected", len(results))
    return results


def _parse_nsp_json_scheme(s: dict) -> Optional[dict]:
    """Parse a single NSP JSON scheme object."""
    name = s.get("schemeName") or s.get("scheme_name") or s.get("name")
    if not name:
        return None
    return {
        "name":        name,
        "amount":      s.get("amount") or s.get("awardAmount") or "Varies",
        "deadline":    s.get("lastDate") or s.get("closingDate") or "Varies",
        "eligibility": s.get("eligibility") or s.get("description") or "Check NSP for details.",
        "link":        s.get("applyLink") or s.get("link") or "https://scholarships.gov.in",
        "type":        "central",
        "source":      "scholarships.gov.in",
        "categories":  _guess_categories(name + " " + (s.get("eligibility") or "")),
    }


def _nsp_static_fallback() -> list[dict]:
    """
    Curated list of current NSP schemes (updated periodically in code).
    Used when live scraping is blocked. Manually verify and update yearly.
    """
    schemes = [
        {
            "name":        "Central Sector Scheme of Scholarships for College & University Students",
            "amount":      "₹10,000 – ₹20,000",
            "deadline":    "2025-12-31",
            "eligibility": "12th pass students with top 20 percentile. Family income below ₹4.5 lakh.",
            "link":        "https://scholarships.gov.in",
            "type":        "central",
            "categories":  ["General", "OBC", "EWS"],
            "qualifications": ["undergraduate", "postgraduate"],
            "max_income":  450000,
            "min_marks":   80,
            "source":      "scholarships.gov.in (static)",
        },
        {
            "name":        "Post Matric Scholarship Scheme for Scheduled Caste Students",
            "amount":      "₹1,200 – ₹7,800",
            "deadline":    "2025-11-30",
            "eligibility": "SC students enrolled in post-matriculation courses. Income below ₹2.5 lakh.",
            "link":        "https://scholarships.gov.in",
            "type":        "central",
            "categories":  ["SC"],
            "qualifications": ["class11", "class12", "diploma", "undergraduate", "postgraduate"],
            "max_income":  250000,
            "source":      "scholarships.gov.in (static)",
        },
        {
            "name":        "Pre-Matric Scholarship Scheme for SC Students (Class 9–10)",
            "amount":      "₹600 – ₹3,500",
            "deadline":    "2025-11-30",
            "eligibility": "SC students in class 9 and 10. Income below ₹2.5 lakh.",
            "link":        "https://scholarships.gov.in",
            "type":        "central",
            "categories":  ["SC"],
            "qualifications": ["class9", "class10"],
            "max_income":  250000,
            "source":      "scholarships.gov.in (static)",
        },
        {
            "name":        "Post Matric Scholarship for ST Students",
            "amount":      "₹1,200 – ₹7,800",
            "deadline":    "2025-11-30",
            "eligibility": "ST students pursuing post-matriculation courses. Income below ₹2.5 lakh.",
            "link":        "https://scholarships.gov.in",
            "type":        "central",
            "categories":  ["ST"],
            "qualifications": ["class11", "class12", "diploma", "undergraduate", "postgraduate"],
            "max_income":  250000,
            "source":      "scholarships.gov.in (static)",
        },
        {
            "name":        "Merit cum Means Scholarship for Minority Students",
            "amount":      "₹25,000",
            "deadline":    "2025-10-31",
            "eligibility": "Minority community students in technical/professional courses. 50%+ marks, income below ₹2.5 lakh.",
            "link":        "https://scholarships.gov.in",
            "type":        "central",
            "categories":  ["OBC"],
            "qualifications": ["undergraduate", "postgraduate"],
            "max_income":  250000,
            "min_marks":   50,
            "source":      "scholarships.gov.in (static)",
        },
        {
            "name":        "National Means cum Merit Scholarship (NMMS)",
            "amount":      "₹12,000",
            "deadline":    "Varies",
            "eligibility": "Class 9 students who passed class 8 with 55%+ marks. Income below ₹3.5 lakh.",
            "link":        "https://scholarships.gov.in",
            "type":        "central",
            "categories":  ["General", "OBC", "SC", "ST", "EWS"],
            "qualifications": ["class9"],
            "max_income":  350000,
            "min_marks":   55,
            "source":      "scholarships.gov.in (static)",
        },
        {
            "name":        "Pragati Scholarship for Girl Students (AICTE)",
            "amount":      "₹50,000",
            "deadline":    "2025-12-31",
            "eligibility": "Girl students in AICTE-approved technical degree/diploma. Income below ₹8 lakh.",
            "link":        "https://www.aicte-india.org",
            "type":        "central",
            "categories":  ["General", "OBC", "SC", "ST", "EWS"],
            "gender":      "female",
            "qualifications": ["diploma", "undergraduate"],
            "max_income":  800000,
            "source":      "scholarships.gov.in (static)",
        },
        {
            "name":        "Saksham Scholarship for Specially Abled Students (AICTE)",
            "amount":      "₹50,000",
            "deadline":    "2025-12-31",
            "eligibility": "Specially-abled students (40%+ disability) in AICTE-approved technical institutions.",
            "link":        "https://www.aicte-india.org",
            "type":        "central",
            "categories":  ["General", "OBC", "SC", "ST", "EWS"],
            "qualifications": ["diploma", "undergraduate"],
            "max_income":  800000,
            "disability_only": True,
            "source":      "scholarships.gov.in (static)",
        },
    ]
    return [normalise(s) for s in schemes]


# ── Helper Classifiers ────────────────────────────────────────────────────────

def _guess_type(text: str) -> str:
    text = text.lower()
    if any(w in text for w in ["central", "national", "india", "ugc", "aicte", "nsp", "mhrd", "ministry"]):
        return "central"
    if any(w in text for w in ["state", "pradesh", "karnataka", "maharashtra", "tamil", "kerala",
                                "rajasthan", "gujarat", "punjab", "haryana", "bihar", "up", "mp"]):
        return "state"
    if any(w in text for w in ["foundation", "trust", "ngo", "corporate", "private", "company",
                                "reliance", "tata", "hdfc", "infosys", "wipro", "buddy"]):
        return "private"
    return "central"


def _guess_categories(text: str) -> list[str]:
    text = text.lower()
    cats = []
    if "general" in text or "open" in text or "all categories" in text or "all students" in text:
        return ["General", "OBC", "SC", "ST", "EWS"]
    if "sc" in text or "scheduled caste" in text or "dalit" in text:
        cats.append("SC")
    if "st" in text or "scheduled tribe" in text or "tribal" in text or "adivasi" in text:
        cats.append("ST")
    if "obc" in text or "other backward" in text:
        cats.append("OBC")
    if "ews" in text or "economically weaker" in text:
        cats.append("EWS")
    if "minority" in text or "muslim" in text or "christian" in text or "sikh" in text:
        cats.append("OBC")
    return cats if cats else ["General", "OBC", "SC", "ST", "EWS"]


def _guess_gender(text: str) -> str:
    text = text.lower()
    if "girl" in text or "women" in text or "female" in text or "woman" in text:
        return "female"
    if "boy" in text or "men only" in text or "male only" in text:
        return "male"
    return "all"


def _is_disability(text: str) -> bool:
    text = text.lower()
    return any(w in text for w in ["disability", "disabled", "divyang", "differently abled",
                                    "specially abled", "handicapped", "pwd"])


def _clean_amount(text: str) -> str:
    text = text.strip()
    if not text or text.lower() in ("n/a", "na", "-", ""):
        return "Varies"
    # Ensure rupee symbol present
    if re.search(r"\d", text) and "₹" not in text and "rs" not in text.lower():
        text = "₹" + text
    return text[:80]


def _parse_deadline(text: str) -> str:
    text = text.strip()
    if not text or text.lower() in ("n/a", "na", "-", "ongoing", "rolling", ""):
        return "Varies"
    # Try to parse and reformat to YYYY-MM-DD
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%d %b %Y", "%d %B %Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return text[:30]  # Return as-is if can't parse


# ── Deduplication ─────────────────────────────────────────────────────────────

def deduplicate(scholarships: list[dict]) -> list[dict]:
    """Remove duplicates by name similarity (case-insensitive, normalised)."""
    seen   = {}
    unique = []
    for s in scholarships:
        key = re.sub(r"[^a-z0-9]", "", s["name"].lower())[:60]
        if key not in seen:
            seen[key] = True
            unique.append(s)
    log.info("Deduplicated: %d → %d entries", len(scholarships), len(unique))
    return unique


# ── Selenium Helper (Optional) ────────────────────────────────────────────────

def get_selenium_driver():
    """Return a headless Chrome WebDriver, or None if unavailable."""
    if not SELENIUM_AVAILABLE:
        log.warning("Selenium not installed — skipping JS-rendered scraping.")
        return None
    try:
        opts = ChromeOptions()
        opts.add_argument("--headless")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--window-size=1280,900")
        opts.add_argument(f"--user-agent={random.choice(USER_AGENTS)}")
        driver = webdriver.Chrome(options=opts)
        log.info("Selenium Chrome driver started.")
        return driver
    except Exception as e:
        log.warning("Could not start Selenium driver: %s", e)
        return None


# ── Optional Source 4: JS-Heavy Portal via Selenium ──────────────────────────

def scrape_with_selenium(url: str, source_name: str) -> list[dict]:
    """
    Generic Selenium scraper for JavaScript-rendered scholarship pages.
    Add this to the pipeline if a source requires JS execution.
    """
    driver = get_selenium_driver()
    if not driver:
        return []

    results = []
    try:
        log.info("Selenium: loading %s", url)
        driver.get(url)
        polite_delay(3, 6)

        # Wait for content
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "article"))
        )
        soup = BeautifulSoup(driver.page_source, "html.parser")
        cards = soup.select("article, .card, [class*='scholarship']")

        for card in cards:
            title_el = card.select_one("h2, h3, h4, [class*='title']")
            link_el  = card.select_one("a[href]")
            elig_el  = card.select_one("p, [class*='desc']")

            title = safe_text(title_el)
            if not title:
                continue

            results.append(normalise({
                "name":        title,
                "eligibility": safe_text(elig_el)[:400],
                "link":        link_el["href"] if link_el else url,
                "source":      source_name,
                "type":        _guess_type(title),
                "categories":  _guess_categories(title),
            }))

    except Exception as e:
        log.error("Selenium scrape failed for %s: %s", url, e)
    finally:
        driver.quit()

    log.info("Selenium: got %d results from %s", len(results), source_name)
    return results


# ── Main Pipeline ─────────────────────────────────────────────────────────────

def run_pipeline() -> list[dict]:
    log.info("=" * 60)
    log.info("Scholarship Scraper — starting at %s", datetime.utcnow().isoformat())
    log.info("=" * 60)

    session = get_session()
    all_results: list[dict] = []

    # ── Each source is wrapped in try/except so one failure never stops others ──
    scrapers = [
        ("Scholarise.in", scrape_scholarise),
        ("Buddy4Study",   scrape_buddy4study),
        ("NSP",           scrape_nsp),
    ]

    for name, fn in scrapers:
        try:
            results = fn(session)
            log.info("%s: +%d scholarships", name, len(results))
            all_results.extend(results)
        except Exception as e:
            log.error("CRITICAL FAILURE in %s scraper: %s — continuing…", name, e)

    # Deduplicate
    all_results = deduplicate(all_results)

    log.info("=" * 60)
    log.info("Total after merge + dedup: %d scholarships", len(all_results))
    log.info("=" * 60)
    return all_results


def save(data: list[dict], path: Path = OUTPUT_FILE) -> None:
    """Write scholarships to JSON file."""
    payload = {
        "meta": {
            "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "count": len(data),
            "sources": list({s.get("source", "unknown") for s in data}),
        },
        "scholarships": data,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Saved %d scholarships → %s", len(data), path)
    # Also save with metadata separately for debugging
    meta_path = path.parent / "scholarships_meta.json"
    meta_path.write_text(json.dumps(payload["meta"], ensure_ascii=False, indent=2), encoding="utf-8")


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scholarship data scraper")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--output", default=str(OUTPUT_FILE), help="Output JSON file path")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    OUTPUT_FILE = Path(args.output)

    data = run_pipeline()

    if not data:
        log.error("No scholarship data collected! Check scraper logs.")
        sys.exit(1)

    save(data)
    log.info("Done. ✓")
